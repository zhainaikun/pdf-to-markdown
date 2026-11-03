# Conversion and reading options

`--references separate` (default) moves a detected reference-list section to
`paper.references.md`, preserving PDF page markers. In-text citations stay in
the body. `--references inline` keeps the list in the body; any older sidecar
is not part of that run (consult the index/manifest). Detection uses standalone
References/Bibliography/Literature cited/参考文献 headings and stops at recognized
appendix, supplementary, acknowledgements, funding or data-availability headings.
Unheaded lists and reference-only partial selections may remain inline; check
the source when exhaustive bibliography coverage matters.

`--strip-headers-footers` removes repeated native text found in top/bottom 9%
page margins, only matching complete Markdown lines. It intentionally leaves
unmatched or combined footer lines. `--dedupe-captions` removes only identical
Figure/Fig./图 caption paragraphs after their first occurrence. Both are opt-in;
removed text is retained in the quality report, and unique captions stay intact.

Spacing recovery uses PDF glyph gaps, exact token matches and no dictionary.
Applied repairs are listed in quality `transformations`. `--no-fix-spacing`
disables repairs but still reports geometry evidence. Long English runs generate
`suspected_joined_words` warnings; long technical words may be false positives,
and shorter glued words may escape detection. Verify consequential passages.

The reader CLI emits plain text with source-page markers and, only when
truncated, a continuation offset. Keep all filters unchanged on continuation.
The Python `read_excerpt` API retains its metadata dictionary for programmatic
coverage checks; `render_excerpt` produces the exact compact CLI payload.
Search excerpts do not establish complete page coverage.

Use `--pages 1,3,5-10` for selected source pages; default conversion selects all.
Directory input requires `--output-dir`, optionally `--recursive`; check the
batch result for per-file failures. Cached artifacts include separate references
and cleanup options. `--force` rebuilds without deleting prior asset generations.
