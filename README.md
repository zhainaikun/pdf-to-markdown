# pdf-to-markdown

Local PDF preprocessing for agents reading papers: convert once, read the full
Markdown directly for close reading, or selected pages for screening/questions.

The converter makes no language-model API calls. The resulting text still costs
tokens when read by an agent. Savings depend on task scope, host behavior, actual
model/tokenizer and avoided image/repeated input; no fixed saving rate is claimed.

## Install and use

Requires Python 3.11+. Use your environment's approved Python interpreter by its
full path. Install `requirements.txt`; direct dependencies are pinned to the
versions exercised by the regression suite. See [platform setup](references/setup.md)
for PowerShell and POSIX examples. A local skill installation consists of this
folder and its SKILL.md, scripts, requirements and references.

Command argument examples (`<PYTHON>` is a placeholder for that full path):

```text
<PYTHON> scripts/pdf_to_md.py paper.pdf results/paper.md
<PYTHON> scripts/read_md.py results/paper.index.json --pages 2-4 --max-chars 12000
<PYTHON> scripts/read_md.py results/paper.index.json --search "control group"
<PYTHON> scripts/read_md.py results/paper.index.json --section "Methods"
<PYTHON> scripts/pdf_to_md.py papers --output-dir results --recursive
```

`--section` finds pages with matching detected headings, not the full span of a
section. Follow subsequent pages when needed. The plain-text reader's
`[continue --offset N]` marker supports incremental reading. Preserve the same
filters when continuing. An absent search match does not prove a concept is absent.

Conversion options: `--pages 1,3,5-10`, `--no-images`, `--no-tables`,
`--images-dir ROOT`, `--tables-dir ROOT`, `--ocr`, `--force`,
`--references separate|inline`, `--strip-headers-footers`, `--dedupe-captions`,
`--no-fix-spacing`. See [cleanup details](references/options.md).

OCR is disabled by default. Enable local OCR deliberately when needed; it may
require additional runtime/models. Low-text pages are flagged even when the
command succeeds. Image regions include detected pictures/formulas and are
rendered to PNG with ordinary links; they are not necessarily complete numbered
figures. No remote conversion service is called by this skill.

## Outputs

| Output | Purpose |
| --- | --- |
| `paper.md` | Selected-page body with original PDF page markers |
| `paper.references.md` | Reference list separated by default; read as needed |
| `paper.index.md` | Navigation for targeted questions |
| `paper.index.json` | Page files, headings, bookmarks, line ranges and asset paths |
| `paper.quality.json` | Selected-page coverage and extraction warnings |
| `paper.manifest.json` | Source/options/version signature and artifact hashes |
| `paper_assets/` | Per-page Markdown and isolated image/CSV generations |
| `batch-index.json` | Batch results, including individual failures |

Custom asset directories are roots, not flat shared output folders. Generated
links encode spaces and Unicode. Keep the complete output bundle together when
sharing. Old generations remain on disk but are excluded from the current index.
See [cache and portability details](references/setup.md#output-and-cache).

## Agent behavior

SKILL.md covers PDF reading, summarization, question answering and multi-paper
comparison, as well as explicit conversion. Read full Markdown directly for close
reading; consult indexes/reports for targeted questions or anomalies. Use source pages to
check equations, reading order and important tables. Complete-reading requests
must cover all requested pages, rather than silently becoming a summary.

The skill cannot guarantee attachment interception in every agent product. The
host must expose local files and invoke the skill; a strict upload-first pipeline
needs host integration. See the [suggested host instruction](references/setup.md#host-integration).

## Verification

```text
<PYTHON> -m unittest discover -s tests -v
```

The suite generates PDFs locally and checks caching, source changes, missing
assets, invalid page ranges, links, images, quality warnings, bounded reading,
source preservation and batch failures. It uses no paid model API or network.
The tested local environment is Windows / Python 3.14 / PyMuPDF 2.0 /
PyMuPDF4LLM 2.0. Other OS/Python combinations and optional OCR are not certified by
this run. The v2 benchmark uses three local papers with preserved input payloads;
its text token counts are not billed usage or a guarantee for other documents.

## License

The original repository did not include a LICENSE file. This revision does not
assign a license on the author's behalf. Choose and add a license before
advertising reuse terms; dependency licenses are distributed with their packages.
