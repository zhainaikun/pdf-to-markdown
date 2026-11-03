#!/usr/bin/env python3
"""Local PDF conversion with verifiable cache and bounded-reading artifacts."""
from __future__ import annotations
import argparse
import contextlib
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote
from text_cleanup import repair_spacing, suspect_words, margin_keys, clean_page, split_references

SCHEMA = 3


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(text)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def relative(path, base):
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:
        return path.as_uri()


def link(path, base):
    return quote(relative(path, base), safe='/:')


def parse_pages(value, count=None):
    pages = set()
    for item in value.split(','):
        match = re.fullmatch(r'\s*([1-9]\d*)\s*(?:-\s*([1-9]\d*)\s*)?', item)
        if not match:
            raise ValueError('Pages must be positive numbers/ranges, e.g. 1,3,5-10')
        first, last = int(match[1]), int(match[2] or match[1])
        if last < first:
            raise ValueError(f'Reversed page range: {item}')
        if count is not None and last > count:
            raise ValueError(f'Page {last} exceeds document length {count}')
        if last > 1_000_000:
            raise ValueError('Page number is unreasonably large')
        pages.update(range(first - 1, last))
    return sorted(pages)


def safe_stem(name):
    return re.sub(r'[^\w-]+', '_', name).strip('_')[:60] or 'document'


def cache_valid(manifest, key):
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data['cache_key'] != key or not data['artifacts']:
            return None
        for artifact in data['artifacts']:
            path = Path(artifact['path'])
            if not path.is_file() or digest(path) != artifact['sha256']:
                return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def extract_tables_for_page(page, folder, base, warnings):
    records = []
    try:
        tables = page.find_tables().tables
        for i, table in enumerate(tables, 1):
            try:
                rows = table.extract()
                if not rows or not any(any(c for c in row) for row in rows):
                    continue
                empty_columns = [col + 1 for col in range(max(map(len, rows)))
                                 if all(col >= len(row) or row[col] is None or not str(row[col]).strip() for row in rows)]
                if empty_columns:
                    warnings.append({'page': page.number + 1, 'code': 'table_empty_columns',
                                     'detail': f'Detected table {i} has empty columns {empty_columns}; these may be layout artifacts. Values are preserved; verify against the source.'})
                path = folder / f'p{page.number + 1:04d}_table_{i:03d}.csv'
                with path.open('w', encoding='utf-8', newline='') as f:
                    csv.writer(f).writerows([['' if c is None else str(c).strip() for c in row] for row in rows])
                records.append({'page': page.number + 1, 'file': relative(path, base), 'path': str(path),
                                'rows': len(rows), 'cols': max(map(len, rows)), 'bbox': list(table.bbox)})
            except Exception as exc:
                warnings.append({'page': page.number + 1, 'code': 'table_extraction_failed', 'detail': f'{type(exc).__name__}: {exc}'})
    except Exception as exc:
        warnings.append({'page': page.number + 1, 'code': 'table_detection_failed', 'detail': f'{type(exc).__name__}: {exc}'})
    return records


def convert(input_path, output_path, images_dir=None, tables_dir=None, pages=None,
            extract_imgs=True, extract_tables=True, force=False, ocr=False,
            references='separate', strip_headers_footers=False, dedupe_captions=False,
            fix_spacing=True):
    import pymupdf
    import pymupdf4llm
    source, output = input_path.expanduser().resolve(), output_path.expanduser().resolve()
    if references not in ('separate', 'inline'):
        raise ValueError('references must be separate or inline')
    if not source.is_file() or source.suffix.lower() != '.pdf':
        raise ValueError(f'Expected an existing PDF file: {source}')
    if output == source or output.suffix.lower() != '.md':
        raise ValueError('Output must be a .md file distinct from the input PDF')
    manifest_path = output.with_suffix('.manifest.json')
    index_path, overview_path = output.with_suffix('.index.json'), output.with_suffix('.index.md')
    quality_path = output.with_suffix('.quality.json')
    asset_root = output.parent / (output.stem + '_assets')
    image_root = (images_dir or asset_root / 'images').expanduser().resolve()
    table_root = (tables_dir or asset_root / 'tables').expanduser().resolve()
    versions = {name: importlib.metadata.version(name) for name in ('pymupdf', 'pymupdf4llm')}
    source_hash = digest(source)
    with pymupdf.open(source) as doc:
        if doc.needs_pass:
            raise ValueError('Encrypted PDF requires an unlocked local copy')
        selected = parse_pages(pages, len(doc)) if isinstance(pages, str) else pages
        selected = list(range(len(doc))) if selected is None else sorted(set(selected))
        if not selected or any(not isinstance(p, int) or p < 0 or p >= len(doc) for p in selected):
            raise ValueError(f'Pages must select at least one page within 1..{len(doc)}')
        key = {'schema': SCHEMA, 'converter_sha256': digest(Path(__file__)), 'source': str(source),
               'source_sha256': source_hash, 'pages': selected, 'images': extract_imgs, 'tables': extract_tables,
               'ocr': ocr, 'image_root': str(image_root), 'table_root': str(table_root), 'versions': versions,
               'cleanup_sha256': digest(Path(__file__).with_name('text_cleanup.py')),
               'references': references, 'strip_headers_footers': strip_headers_footers,
               'dedupe_captions': dedupe_captions, 'fix_spacing': fix_spacing}
        cached = None if force else cache_valid(manifest_path, key)
        if cached:
            return {'status': 'cached', 'markdown': str(output), 'index': str(overview_path), 'warnings': cached['warning_count']}
        # Unique generations: never enumerate or recursively delete shared user directories.
        asset_root.mkdir(parents=True, exist_ok=True)
        generation = Path(tempfile.mkdtemp(prefix='run-', dir=asset_root))
        page_dir = generation / 'pages'
        page_dir.mkdir()
        image_folder = table_folder = None
        if extract_imgs:
            image_root.mkdir(parents=True, exist_ok=True)
            image_folder = Path(tempfile.mkdtemp(prefix='run-', dir=image_root))
        if extract_tables:
            table_root.mkdir(parents=True, exist_ok=True)
            table_folder = Path(tempfile.mkdtemp(prefix='run-', dir=table_root))
        warnings, records, full, artifacts = [], [], [], []
        reference_parts, changes, seen_captions = [], [], set()
        in_references = False
        margins = margin_keys(doc, selected) if strip_headers_footers else set()
        parser_log = io.StringIO()
        kwargs = dict(pages=selected, page_chunks=True, use_ocr=ocr, write_images=False,
                      embed_images=False, show_progress=False)
        with contextlib.redirect_stdout(parser_log):
            chunks = pymupdf4llm.to_markdown(doc, **kwargs)
        if not isinstance(chunks, list) or len(chunks) != len(selected):
            raise ValueError('Converter did not return one chunk per selected page; no complete result published')
        chunk_map = {chunk.get('metadata', {}).get('page_number'): chunk for chunk in chunks}
        if set(chunk_map) != {p + 1 for p in selected}:
            raise ValueError('Converter page metadata does not match requested pages')
        image_paths = []
        for pno in selected:
            page, chunk = doc[pno], chunk_map[pno + 1]
            text = chunk['text']
            extracted_text = text
            repaired, repairs = repair_spacing(text, page)
            if repairs:
                changes.append({'page': pno + 1, 'kind': 'spacing', 'applied': fix_spacing, 'repairs': repairs})
                if fix_spacing:
                    text = repaired
                else:
                    warnings.append({'page': pno + 1, 'code': 'joined_words_geometry', 'detail': repairs})
            remaining = suspect_words(text)
            if remaining:
                warnings.append({'page': pno + 1, 'code': 'suspected_joined_words', 'detail': remaining})
            text, removed = clean_page(text, margins, seen_captions, strip_headers_footers, dedupe_captions)
            if removed:
                changes.append({'page': pno + 1, 'kind': 'removed', 'items': removed})
            if references == 'separate':
                text, ref_text, in_references = split_references(text, in_references)
                if ref_text.strip():
                    reference_parts.append(f'<!-- PDF page: {pno + 1} -->\n\n{ref_text.strip()}\n\n')
            native = page.get_text().strip()
            if len(native) < 40:
                warnings.append({'page': pno + 1, 'code': 'low_native_text', 'detail': 'Possible scan, figure-only or blank page; inspect before claiming coverage.'})
            if len(extracted_text.strip()) < 40:
                warnings.append({'page': pno + 1, 'code': 'low_extracted_text', 'detail': 'Little text extracted; targeted review or OCR may be needed.'})
            if '\ufffd' in extracted_text:
                warnings.append({'page': pno + 1, 'code': 'replacement_characters', 'detail': 'Verify affected passages against the source.'})
            used_images = []
            if image_folder:
                # Avoid backend path normalization; save bytes through pathlib.
                for number, box in enumerate(chunk.get('page_boxes', []), 1):
                    if box.get('class') not in ('picture', 'formula'):
                        continue
                    try:
                        rect = pymupdf.Rect(box['bbox']) & page.rect
                        if rect.is_empty or rect.is_infinite:
                            raise ValueError('Empty or invalid image bounds')
                        path = image_folder / f'p{pno + 1:04d}_asset_{number:03d}.png'
                        path.write_bytes(page.get_pixmap(clip=rect, dpi=150).tobytes('png'))
                        used_images.append(path)
                    except Exception as exc:
                        warnings.append({'page': pno + 1, 'code': 'image_extraction_failed', 'detail': f'{type(exc).__name__}: {exc}'})
                if page.get_images() and not used_images:
                    warnings.append({'page': pno + 1, 'code': 'images_not_localized', 'detail': 'Embedded images exist but no image region was exported; inspect the source page when needed.'})
                image_paths.extend(used_images)
            def readable_text(base):
                return re.sub(r'!\[([^\]]*)\]\(([^\n]+?)\)', lambda m: f'[{m[1] or "Figure asset"}]({m[2]})', text)
            tables = extract_tables_for_page(page, table_folder, output.parent, warnings) if table_folder else []
            page_file = page_dir / f'p{pno + 1:04d}.md'
            def assemble(base):
                body = f'<!-- PDF page: {pno + 1} -->\n\n' + readable_text(base).strip() + '\n'
                if used_images:
                    body += '\nVisual regions (open only when needed; numbering is not the paper figure number):\n'
                    for number, image in enumerate(used_images, 1):
                        body += f'- [Page {pno + 1} visual region {number}]({link(image, base)})\n'
                if tables:
                    body += '\nCSV tables (detected regions; verify against the source):\n'
                    for t in tables:
                        body += f'- [Page {pno + 1} table ({t["rows"]} x {t["cols"]})]({link(Path(t["path"]), base)})\n'
                return body
            body = assemble(output.parent)
            line_start = sum(part.count('\n') for part in full) + 1
            full.append(body + '\n')
            atomic_write(page_file, assemble(page_file.parent))
            artifacts.append(page_file)
            artifacts.extend(Path(t['path']) for t in tables)
            headings = [m[2].strip() for m in re.finditer(r'(?m)^(#{1,6})\s+(.+)$', text)]
            records.append({'page': pno + 1, 'file': relative(page_file, output.parent),
                            'line_start': line_start, 'line_end': line_start + body.count('\n') - 1,
                            'characters': len(text), 'native_characters': len(native), 'headings': headings,
                            'tables': tables, 'images': [relative(p, output.parent) for p in used_images]})
        if digest(source) != source_hash:
            raise ValueError('Source PDF changed during conversion; retry with a stable file')
        artifacts.extend(image_paths)
        referenced = {v for record in records for v in record['images']}
        for image in image_paths:
            if relative(image, output.parent) not in referenced:
                warnings.append({'page': None, 'code': 'unmapped_image', 'detail': relative(image, output.parent)})
        coverage = {'source_page_count': len(doc), 'selected_pages': [p+1 for p in selected], 'complete_document_selected': len(selected) == len(doc)}
        quality = {'status': 'needs_review' if warnings else 'no_automatic_warnings', 'coverage': coverage, 'warnings': warnings,
                   'transformations': changes, 'references_mode': references,
                   'limitations': ['Heuristics do not certify reading order, equations, figure completeness or table accuracy.',
                                   'No automatic warning does not mean lossless extraction.'], 'ocr_enabled': ocr}
        index = {'schema': SCHEMA, 'source': str(source), 'source_sha256': source_hash, 'markdown': output.name,
                 'references': output.with_suffix('.references.md').name if references == 'separate' else None,
                 'coverage': coverage, 'pages': records, 'quality': quality_path.name, 'bookmarks': doc.get_toc()}
        overview = [f'# Reading index: {source.name}', '', f'Selected {len(selected)} of {len(doc)} pages. Quality: {quality["status"]}.',
                    f'Warnings: {len(warnings)}. See [{quality_path.name}]({link(quality_path, output.parent)}).',
                    'Read relevant page files; inspect images only when needed. Full reading requires every selected page.', '']
        for record in records:
            title = '; '.join(record['headings']) or '(no heading detected)'
            overview.append(f'- [Page {record["page"]}]({quote(record["file"], safe="/:")}): {title[:200]} | {record["characters"]} characters | {len(record["tables"])} tables | {len(record["images"])} image links')
        for path, value in ((index_path, index), (quality_path, quality)):
            atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        atomic_write(overview_path, '\n'.join(overview) + '\n')
        atomic_write(output, ''.join(full))
        if references == 'separate':
            ref_path = output.with_suffix('.references.md')
            atomic_write(ref_path, ''.join(reference_parts) or '<!-- No reference section detected in selected pages. -->\n')
            artifacts.append(ref_path)
        if parser_log.getvalue().strip():
            atomic_write(generation / 'parser.log', parser_log.getvalue())
        artifacts.extend([output, index_path, overview_path, quality_path])
        manifest = {'cache_key': key, 'warning_count': len(warnings), 'artifacts': [{'path': str(p), 'sha256': digest(p)} for p in sorted(set(artifacts))]}
        atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        return {'status': 'converted', 'markdown': str(output), 'index': str(overview_path), 'pages': len(selected), 'warnings': len(warnings)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='PDF file or directory of PDFs')
    parser.add_argument('output', nargs='?', type=Path, help='Single PDF output .md')
    parser.add_argument('--output-dir', type=Path, help='Destination for batch conversion')
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--images-dir', type=Path, help='Image root; assets get isolated subdirectories')
    parser.add_argument('--tables-dir', type=Path, help='CSV root; assets get isolated subdirectories')
    parser.add_argument('--pages', help='1-based pages, e.g. 1,3,5-10')
    parser.add_argument('--no-images', action='store_true')
    parser.add_argument('--no-tables', action='store_true')
    parser.add_argument('--ocr', action='store_true', help='Opt into local backend OCR; may need extra runtime/models')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--references', choices=('separate', 'inline'), default='separate')
    parser.add_argument('--strip-headers-footers', action='store_true')
    parser.add_argument('--dedupe-captions', action='store_true')
    parser.add_argument('--no-fix-spacing', action='store_true')
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    batch = source.is_dir()
    if batch:
        if args.output or not args.output_dir:
            parser.error('Directory input requires --output-dir and no positional output')
        files = sorted(p for p in (source.rglob('*') if args.recursive else source.iterdir()) if p.is_file() and p.suffix.lower() == '.pdf')
        if not files:
            parser.error('No PDFs found')
    else:
        if args.output_dir or args.recursive:
            parser.error('--output-dir/--recursive are for directory input')
        files = [source]
    results = []
    for pdf in files:
        if batch:
            identity = hashlib.sha256(pdf.relative_to(source).as_posix().encode()).hexdigest()[:12]
            output = args.output_dir / f'{safe_stem(pdf.stem)}-{identity}' / 'paper.md'
        else:
            output = args.output or pdf.with_suffix('.md')
        try:
            result = convert(pdf, output, args.images_dir, args.tables_dir, args.pages, not args.no_images, not args.no_tables, args.force, args.ocr,
                             args.references, args.strip_headers_footers, args.dedupe_captions, not args.no_fix_spacing)
        except Exception as exc:
            result = {'status': 'failed', 'source': str(pdf), 'error': f'{type(exc).__name__}: {exc}'}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    if batch:
        atomic_write(args.output_dir / 'batch-index.json', json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    return 1 if any(r['status'] == 'failed' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
