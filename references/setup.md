# Setup and host integration

Requires Python 3.11 or newer. Respect the user's interpreter rules. Paths below
are examples to replace, not fixed installation locations. The conversion script
and read helper are located relative to this skill's installation directory.

## Windows PowerShell

```powershell
$PdfPython = 'C:\path\to\approved\python.exe'
$PdfSkill = 'C:\path\to\pdf-to-markdown'
& $PdfPython -m pip install -r "$PdfSkill\requirements.txt"
& $PdfPython "$PdfSkill\scripts\pdf_to_md.py" 'C:\papers\paper.pdf' 'C:\results\paper.md'
& $PdfPython "$PdfSkill\scripts\read_md.py" 'C:\results\paper.index.json' --pages 1-3
```

An isolated environment is recommended where permitted. If local rules require
a particular interpreter, use that interpreter and the permitted dependency
location instead of silently switching interpreters.

## Linux/macOS shell

```sh
PDF_PYTHON=/absolute/path/to/python3
PDF_SKILL=/absolute/path/to/pdf-to-markdown
"$PDF_PYTHON" -m pip install -r "$PDF_SKILL/requirements.txt"
"$PDF_PYTHON" "$PDF_SKILL/scripts/pdf_to_md.py" paper.pdf result/paper.md
```

Check imports, not merely whether a venv directory exists. On import failure,
report the missing package and install the tested requirements in the selected
environment. No model API key is required for this converter. OCR is optional;
backend/model availability varies by platform and has not been validated in this
release's regression suite.

## Host integration

Suggested instruction for an agent whose host exposes attachments as local files:

> When the user supplies a PDF for reading or analysis, invoke pdf-to-markdown
> on the local file before loading its contents into model context. Read the
> full Markdown directly for close reading, or selected pages for screening.
> Consult the index/quality report only for targeted questions or anomalies. Inspect images only
> as needed. Preserve full coverage for full-reading tasks.

This instruction is useful only after the host exposes the attachment and selects
or invokes the skill. For a strict guarantee, the host's attachment pipeline must
run the converter before submitting PDF content to the model. This repository
contains no host-specific upload hook.

## Output and cache

- `paper.md`: selected-page body with source PDF page markers.
- `paper.references.md`: separately stored reference list by default.
- `paper.index.md`: navigation for targeted questions.
- `paper.index.json`: page files, detected headings, original bookmarks, line ranges,
  image links and detected table metadata.
- `paper.quality.json`: coverage, heuristic warnings, OCR setting and limitations.
- `paper.manifest.json`: cache signature and artifact hashes; written last.
- `paper_assets/`: page files and isolated image/CSV generation directories.

Custom `--images-dir` and `--tables-dir` are roots for isolated subdirectories.
Links are relative where possible and URI-encoded for spaces/non-ASCII characters.
Cross-drive Windows links use file URIs; keep assets beside the Markdown for a
portable bundle. Moving a bundle invalidates its local cache manifest but its
relative reading links remain usable.

Cache checks PDF content, options, converter code, direct dependency versions,
and all generated reading assets. `--force` regenerates into fresh directories.
Old/failed generation directories are deliberately retained, never included in
new indexes, and not automatically deleted from user-selected directories.
Do not run two conversions concurrently to the same output filename. Different
output files can be processed separately. A single-document CLI error returns 1;
batch conversion returns 1 if any input fails and retains per-file outcomes.

## Reading and comparison

`read_md.py --search TEXT` returns literal case-insensitive contextual matches.
`--section TEXT` selects pages containing matching extracted headings; it is not
semantic retrieval or a guaranteed section boundary detector. Without filters,
the helper reads in source-page order with a bounded excerpt. Repeat the same
filters with `--offset N` when `[continue --offset N]` is emitted. For full
close reading, read paper.md directly instead.

For token comparisons, use the same question, model tokenizer and answer scope.
Count all visible input text (skill instructions, indexes, reports, tool outputs,
selected text and repeated turns); count images with the actual model/provider's
method. Record file conversion time separately from LLM usage. Character counts
and provider-free estimates are not billed token measurements. Compare extraction
quality before interpreting apparent savings from omitted content.
