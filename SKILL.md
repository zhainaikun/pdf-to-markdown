---
name: pdf-to-markdown
description: >-
  Use when converting a PDF to Markdown locally (papers, docs, batch). Prefer
  this over feeding the PDF to the model so conversion stays fast and cheap on
  tokens.
---
# PDF → Markdown（本地，省 token）

用 **PyMuPDF4LLM** 在本机把 PDF 转成结构化 Markdown。转换不经过大模型读图/理解，几乎不消耗对话 token；只有你后续要摘要、改写或转发内容时才计 token。

适合：带文本层的论文、报告、说明书。扫描件/纯图片 PDF、复杂公式与无框线表格效果会差一些（可再考虑 Marker/Docling，更慢更重）。

## 目录与脚本

技能目录：`/home/box/agent-data/workflows/pdf-to-markdown`

- 虚拟环境：`<SKILL_DIR>/.venv`
- 转换脚本：`<SKILL_DIR>/scripts/pdf_to_md.py`

## 首次或环境缺失时

```bash
SKILL_DIR=/home/box/agent-data/workflows/pdf-to-markdown
test -d "$SKILL_DIR/.venv" || (cd "$SKILL_DIR" && uv venv .venv && uv pip install --python .venv/bin/python pymupdf pymupdf4llm)
test -f "$SKILL_DIR/scripts/pdf_to_md.py" || echo "missing script"
"$SKILL_DIR/.venv/bin/python" -c "import pymupdf4llm; print('ok')"
```

## 转换

默认输出与 PDF 同目录的同名 `.md`；图放在 `<stem>_images/`。

```bash
SKILL_DIR=/home/box/agent-data/workflows/pdf-to-markdown
"$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/pdf_to_md.py" /path/to/doc.pdf
# 指定输出
"$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/pdf_to_md.py" /path/to/doc.pdf /path/to/out.md
# 选项：--pages 1,3,5-10  --no-images  --force
```

批量：对每个 PDF 跑同一命令；不要把整本 PDF 塞进模型上下文。

## 工作流

1. 拿到 PDF（聊天附件、`/workspace`、或用户电脑经 CopyToBox）。
2. 确认 venv 可用后执行转换。
3. 把生成的 `.md`（及需要的图片目录）交给用户，或按用户指定用 `SendToAgent` 发给其他 bot；附上 md 路径与一两句说明即可。
4. 除非用户要你解读全文，否则不要把整份 md 读进对话；需要时再按需 Read 片段。

## 局限与升级路径

| 情况 | 做法 |
|------|------|
| 扫描件/无文本层 | OCR（如 Tesseract）或更重的 Marker |
| 论文公式/多栏 | 可试 `marker-pdf`（慢、占空间） |
| 复杂表格 | 可试 Docling |

默认始终先用本技能的快速路径。
