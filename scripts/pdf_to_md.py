#!/usr/bin/env python3
"""PDF → Markdown with CSV tables + linked image extraction (token-saving pipeline)."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def parse_pages(pages_str: str) -> list[int]:
    pages: list[int] = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start) - 1, int(end)))
        else:
            pages.append(int(part) - 1)
    return sorted(set(pages))


def safe_stem(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return s[:80] or "doc"


def extract_tables_to_csv(
    doc,
    tables_dir: Path,
    pages: list[int] | None,
) -> list[dict]:
    """Extract detected tables (incl. 三线表-style line tables) to CSV files."""
    tables_dir.mkdir(parents=True, exist_ok=True)
    meta: list[dict] = []
    page_indexes = pages if pages is not None else list(range(len(doc)))
    table_i = 0
    for pno in page_indexes:
        page = doc[pno]
        try:
            finder = page.find_tables()
        except Exception:
            continue
        tables = getattr(finder, "tables", None) or []
        for t in tables:
            try:
                data = t.extract()
            except Exception:
                continue
            if not data or not any(any(cell for cell in row) for row in data):
                continue
            table_i += 1
            fname = f"table_{table_i:03d}_p{pno + 1}.csv"
            fpath = tables_dir / fname
            with fpath.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for row in data:
                    writer.writerow([("" if c is None else str(c).strip()) for c in row])
            meta.append(
                {
                    "index": table_i,
                    "page": pno + 1,
                    "file": fname,
                    "path": str(fpath),
                    "rows": len(data),
                    "cols": max((len(r) for r in data), default=0),
                }
            )
    return meta


def append_assets_index(
    md_text: str,
    tables: list[dict],
    images_rel: str | None,
    image_files: list[str],
) -> str:
    parts = [md_text.rstrip(), "", "---", "", "## Extracted assets (for agents)", ""]
    if tables:
        parts.append("### Tables (CSV)")
        parts.append("")
        parts.append("Prefer reading these CSV files instead of re-parsing table pixels.")
        parts.append("")
        for t in tables:
            parts.append(
                f"- Table {t['index']} (page {t['page']}, {t['rows']}×{t['cols']}): "
                f"`{t['file']}`"
            )
        parts.append("")
    if image_files:
        parts.append("### Figures (images)")
        parts.append("")
        parts.append(
            "When you need to understand a figure, open the image file with a vision/"
            "image-read tool. Do **not** dump every image into context by default."
        )
        parts.append("")
        base = images_rel or "."
        for i, name in enumerate(image_files, 1):
            rel = f"{base}/{name}".replace("\\", "/")
            parts.append(f"- Figure asset {i}: ![]({rel})")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def convert(
    input_path: Path,
    output_path: Path,
    images_dir: Path,
    tables_dir: Path | None = None,
    pages: list[int] | None = None,
    extract_imgs: bool = True,
    extract_tables: bool = True,
    force: bool = False,
) -> None:
    if (
        not force
        and output_path.exists()
        and output_path.stat().st_mtime >= input_path.stat().st_mtime
    ):
        print(f"Cached: {output_path} (use --force to re-extract)")
        return

    import pymupdf
    import pymupdf4llm

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if tables_dir is None:
        tables_dir = output_path.parent / (output_path.stem + "_tables")

    kwargs: dict = {}
    if pages is not None:
        kwargs["pages"] = pages

    image_files: list[str] = []
    images_rel = None
    if extract_imgs:
        images_dir.mkdir(parents=True, exist_ok=True)
        try:
            images_rel = str(images_dir.resolve().relative_to(output_path.parent.resolve()))
        except ValueError:
            images_rel = str(images_dir)
        kwargs.update(
            {
                "write_images": True,
                "image_path": str(images_dir),
                "image_format": "png",
            }
        )

    md_text = pymupdf4llm.to_markdown(str(input_path), **kwargs)

    if extract_imgs and images_dir.exists():
        image_files = sorted(
            p.name
            for p in images_dir.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        )
        print(f"Images in {images_dir}: {len(image_files)}")

    tables_meta: list[dict] = []
    if extract_tables:
        doc = pymupdf.open(str(input_path))
        tables_meta = extract_tables_to_csv(doc, tables_dir, pages)
        doc.close()
        print(f"Tables CSV in {tables_dir}: {len(tables_meta)}")

    md_text = append_assets_index(md_text, tables_meta, images_rel, image_files)
    output_path.write_text(md_text, encoding="utf-8")
    print(f"Written: {output_path} ({len(md_text)} chars)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown + CSV tables + linked images"
    )
    parser.add_argument("input", help="Input PDF")
    parser.add_argument("output", nargs="?", help="Output .md path")
    parser.add_argument(
        "--images-dir",
        required=False,
        help="Directory for extracted figure images (ask the user if unset)",
    )
    parser.add_argument("--tables-dir", help="Directory for table CSV files")
    parser.add_argument("--pages", help="Pages e.g. 1,3,5-10")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--no-tables", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists() or input_path.suffix.lower() != ".pdf":
        print(f"Error: need an existing .pdf, got {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = (
        Path(args.output).resolve()
        if args.output
        else input_path.with_suffix(".md")
    )

    if args.no_images:
        images_dir = output_path.parent / (output_path.stem + "_images")
    elif args.images_dir:
        images_dir = Path(args.images_dir).expanduser().resolve()
    else:
        # Default: sibling <stem>_images/ next to the markdown file
        images_dir = output_path.parent / (output_path.stem + "_images")

    tables_dir = (
        Path(args.tables_dir).expanduser().resolve()
        if args.tables_dir
        else output_path.parent / (output_path.stem + "_tables")
    )
    pages = parse_pages(args.pages) if args.pages else None

    convert(
        input_path=input_path,
        output_path=output_path,
        images_dir=images_dir,
        tables_dir=tables_dir,
        pages=pages,
        extract_imgs=not args.no_images,
        extract_tables=not args.no_tables,
        force=args.force,
    )


if __name__ == "__main__":
    main()
