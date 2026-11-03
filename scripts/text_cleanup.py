"""Conservative, source-grounded whitespace recovery and optional text cleanup."""
import re
import unicodedata
from collections import Counter


def norm(text):
    return unicodedata.normalize('NFKC', text)


def repair_spacing(text, page):
    """Insert spaces only where PDF glyph geometry supports a word boundary.

    Exact native-token matches preserve Markdown ordering and scientific values.
    Ambiguous reconstructions are left untouched, never dictionary-guessed.
    """
    candidates = {}
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            if tuple(line.get('dir', (1, 0))) != (1, 0):
                continue
            chars = [(c, s['size']) for s in line['spans'] for c in s['chars']]
            raw, spaced = '', ''
            previous = None
            for char, size in chars:
                value = norm(char['c'])
                if previous and value and not value.isspace() and not previous[0]['c'].isspace():
                    gap = char['bbox'][0] - previous[0]['bbox'][2]
                    # Below MuPDF's usual space threshold; above ordinary kerning.
                    if gap > max(0.7, min(size, previous[1]) * 0.10):
                        spaced += ' '
                raw += value
                spaced += value
                previous = (char, size)
            # Map each original non-space token to its geometry-spaced equivalent.
            flat = re.sub(r'\s', '', spaced)
            positions = []
            for i, c in enumerate(spaced):
                if not c.isspace():
                    positions.append(i)
            matches = list(re.finditer(r'\S+', raw)) + list(re.finditer(r'[A-Za-z]{6,}', raw))
            for match in matches:
                token = match.group()
                if not re.search(r'[A-Za-z]{6}', token):
                    continue
                cursor = len(re.sub(r'\s', '', raw[:match.start()]))
                end = cursor + len(token)
                if flat[cursor:end] == token and end <= len(positions):
                    replacement = spaced[positions[cursor]:positions[end - 1] + 1]
                    if replacement != token:
                        continued = bool(re.match(r'-\s*$', raw[match.end():]))
                        candidates.setdefault((token, continued), set()).add(replacement)
    repairs = []
    for (token, continued), replacements in sorted(candidates.items(), key=lambda x: -len(x[0][0])):
        if len(replacements) != 1:
            continue
        replacement = next(iter(replacements))
        pattern = r'(?<![\w])' + re.escape(token) + (r'(?=[a-z])' if continued else r'(?![\w])')
        text, count = re.subn(pattern, lambda _: replacement, text)
        if count:
            repairs.append({'before': token, 'after': replacement, 'occurrences': count})
    return text, repairs


def suspect_words(text):
    # Long English runs are evidence of a possible extraction problem, not proof.
    text = re.sub(r'https?://\S+|www\.\S+|\]\([^\n]*?\)', '', text)
    return sorted({word for word in re.findall(r'\b[A-Za-z]{24,}\b', text)
                   if not re.fullmatch(r'[ACGTUN]+', word)})[:20]


def plain(line):
    return re.sub(r'\s+', ' ', re.sub(r'[*_`#]', '', norm(line))).strip()


def margin_keys(doc, selected):
    counts = Counter()
    for pno in selected:
        page = doc[pno]
        keys = set()
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                y0, y1 = line['bbox'][1], line['bbox'][3]
                if y1 < page.rect.height * .09 or y0 > page.rect.height * .91:
                    value = plain(''.join(s['text'] for s in line['spans']))
                    if value:
                        keys.add(value)
        counts.update(keys)
    return {key for key, count in counts.items() if count >= 2}


def clean_page(text, margins, seen_captions, remove_margins=False, dedupe=False):
    removed = []
    if remove_margins:
        lines = []
        for line in text.splitlines():
            if plain(line) in margins:
                removed.append({'kind': 'margin', 'text': line})
            else:
                lines.append(line)
        text = '\n'.join(lines)
    if dedupe:
        parts = []
        for part in re.split(r'\n\s*\n', text):
            key = plain(part)
            if re.match(r'^(?:Figure|Fig\.|图)\s*\d+\b', key, re.I):
                if key in seen_captions:
                    removed.append({'kind': 'duplicate_caption', 'text': part})
                    continue
                seen_captions.add(key)
            parts.append(part)
        text = '\n\n'.join(parts)
    return text, removed


def split_references(text, active=False):
    body, refs = [], []
    for line in text.splitlines(keepends=True):
        heading = plain(line)
        if re.fullmatch(r'(?:\d+[.\s]+)?(?:References|Bibliography|Literature cited|参考文献)', heading, re.I):
            active = True
        elif active and re.match(r'^(?:Appendix\b|Supplementary\b|Supporting information\b|Acknowledg\w*\b|Author contributions\b|Funding\b|Data availability\b)', heading, re.I):
            active = False
        (refs if active else body).append(line)
    return ''.join(body), ''.join(refs), active
