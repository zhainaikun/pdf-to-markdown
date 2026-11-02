# pdf-to-markdown

Token-saving PDF → Markdown skill for AI agents reading lots of papers.

## What it does

1. **Local conversion** (no LLM vision on the whole PDF)
2. **Tables → CSV** (including common ruled / 三线表-style tables via PyMuPDF `find_tables`)
3. **Figures → a folder you choose**, with links listed in the Markdown
4. **Vision only on demand**: when an agent reading the `.md` hits a figure it actually needs, it opens that one image with a vision/read-image tool—not every figure up front

## Install

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

## Usage

Ask where figures should live, then:

```bash
.venv/bin/python scripts/pdf_to_md.py paper.pdf paper.md \
  --images-dir /path/for/figures \
  --tables-dir paper_tables \
  --force
```

## Agent contract (put this in your bot instructions)

- Prefer Markdown text + CSV over pixels.
- Do **not** auto-load every `![](...)`.
- Call vision only for a named figure when captions/tables are not enough.
- Hand off `.md` + paths to other agents with the same rule.

## Layout

```
SKILL.md              # agent recipe
scripts/pdf_to_md.py  # converter
requirements.txt
README.md
```

## License

MIT (suggested; change if you fork under another license)
