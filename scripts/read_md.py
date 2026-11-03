#!/usr/bin/env python3
"""Read a bounded excerpt from a generated index; stdout never dumps the whole corpus by default."""
import argparse
import json
from pathlib import Path
import re
from pdf_to_md import parse_pages


def read_excerpt(index_path, pages=None, search=None, section=None, offset=0, max_chars=12000):
    if offset < 0 or not 1 <= max_chars <= 100000:
        raise ValueError('offset must be nonnegative and max-chars must be 1..100000')
    index_path = Path(index_path).resolve()
    index = json.loads(index_path.read_text(encoding='utf-8'))
    selected = None if pages is None else {p + 1 for p in parse_pages(pages, index['coverage']['source_page_count'])}
    available = {p['page'] for p in index['pages']}
    if selected is not None and not selected <= available:
        raise ValueError(f'Requested pages have not been converted: {sorted(selected - available)}')
    pieces, matched = [], []
    for page in index['pages']:
        if selected is not None and page['page'] not in selected:
            continue
        text = (index_path.parent / page['file']).read_text(encoding='utf-8')
        if section and not any(section.casefold() in h.casefold() for h in page['headings']):
            continue
        if search:
            intervals = []
            for match in re.finditer(re.escape(search), text, flags=re.IGNORECASE):
                start, end = max(0, match.start() - 250), min(len(text), match.end() + 450)
                if intervals and start <= intervals[-1][1]:
                    intervals[-1][1] = max(end, intervals[-1][1])
                else:
                    intervals.append([start, end])
            if not intervals:
                continue
            text = '\n[...]\n'.join(text[start:end] for start, end in intervals)
        matched.append(page['page'])
        pieces.append(text + '\n')
    combined = ''.join(pieces)
    excerpt = combined[offset:offset + max_chars]
    more = offset + len(excerpt) < len(combined)
    return {'matched_pages': matched, 'mode': 'search_snippets' if search else 'selected_pages',
            'section_filter': 'heading-containing pages only; use page ranges for continuation' if section else None,
            'offset': offset, 'next_offset': offset + len(excerpt) if more else None,
            'truncated': more, 'total_characters': len(combined), 'text': excerpt,
            'note': 'Character budget is not a model token count. Search snippets do not establish full-paper coverage.'}


def render_excerpt(result):
    text = result['text']
    if result['offset'] or result['mode'] == 'search_snippets':
        text = '[PDF pages: ' + ','.join(map(str, result['matched_pages'])) + ']\n' + text
    if result['next_offset'] is not None:
        text += f'\n[continue --offset {result["next_offset"]}]'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('index', type=Path)
    parser.add_argument('--pages')
    parser.add_argument('--search', help='Literal case-insensitive search with local context')
    parser.add_argument('--section', help='Find pages containing a matching detected heading')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--max-chars', type=int, default=12000)
    args = parser.parse_args()
    try:
        result = read_excerpt(args.index, args.pages, args.search, args.section, args.offset, args.max_chars)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(render_excerpt(result))


if __name__ == '__main__':
    main()
