"""Synthetic behavioral regression tests; no network or paid model calls."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pdf_to_md as converter
from read_md import read_excerpt
import pymupdf


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.pdf = cls.root / 'sample.pdf'
        doc = pymupdf.open()
        for i in range(2):
            page = doc.new_page()
            page.insert_text((72, 72), f'PAGE_{i+1}_UNIQUE - Methods and scientific results for testing.', fontsize=14)
            for x in (72, 172, 272):
                page.draw_line((x,120),(x,210))
            for y in (120,150,180,210):
                page.draw_line((72,y),(272,y))
            for r in range(3):
                for c in range(2):
                    page.insert_text((80+c*100,140+r*30), f'R{r}C{c}')
            # Embed a real raster with a distinctive pattern.
            pic = pymupdf.Pixmap(pymupdf.csRGB, (0,0,100,100), False)
            pic.clear_with(120)
            pic.set_rect((20,20,80,80), (255,50,20))
            page.insert_image(pymupdf.Rect(72,260,272,460), pixmap=pic)
            page.insert_text((72,480), f'Figure {i+1}: sample colored image.')
        doc.save(cls.pdf)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=self.root))
        self.out = self.dir / 'paper.md'

    def convert(self, **kwargs):
        return converter.convert(self.pdf, self.out, **kwargs)

    def test_cache_respects_pages_and_options(self):
        self.assertEqual(self.convert(pages='1', extract_imgs=False)['status'], 'converted')
        self.assertEqual(self.convert(pages='1', extract_imgs=False)['status'], 'cached')
        self.assertEqual(self.convert(pages='2', extract_imgs=False)['status'], 'converted')
        text = self.out.read_text(encoding='utf-8')
        self.assertIn('PAGE_2_UNIQUE', text)
        self.assertNotIn('PAGE_1_UNIQUE', text)
        self.assertEqual(self.convert(pages='2', extract_imgs=True)['status'], 'converted')

    def test_cache_checks_content_not_mtime(self):
        pdf = self.dir / 'source.pdf'
        shutil.copyfile(self.pdf, pdf)
        converter.convert(pdf, self.out, extract_imgs=False)
        stamp = pdf.stat().st_mtime
        doc = pymupdf.open(pdf)
        doc[0].insert_text((72,520), 'NEW_CONTENT_WITH_OLD_MTIME')
        doc.saveIncr()
        doc.close()
        os.utime(pdf, (stamp, stamp))
        self.assertEqual(converter.convert(pdf, self.out, extract_imgs=False)['status'], 'converted')
        self.assertIn('NEW_CONTENT_WITH_OLD_MTIME', self.out.read_text(encoding='utf-8'))

    def test_missing_or_changed_artifact_invalidates_cache(self):
        self.convert(extract_imgs=False)
        index = json.loads(self.out.with_suffix('.index.json').read_text(encoding='utf-8'))
        (self.dir / index['pages'][0]['file']).unlink()
        self.assertEqual(self.convert(extract_imgs=False)['status'], 'converted')
        self.out.write_text('corrupted', encoding='utf-8')
        self.assertEqual(self.convert(extract_imgs=False)['status'], 'converted')

    def test_invalid_pages(self):
        for value in ('0','-1','3-1','1,','abc','1-3','99999999999'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.convert(pages=value)
        self.assertFalse(self.out.exists())

    def test_assets_are_isolated_and_links_work(self):
        images = self.dir / 'shared images (中文)'
        tables = self.dir / 'shared tables (中文)'
        images.mkdir()
        foreign = images / 'foreign.png'
        foreign.write_bytes(b'foreign')
        self.convert(images_dir=images, tables_dir=tables)
        self.assertEqual(foreign.read_bytes(), b'foreign')
        index = json.loads(self.out.with_suffix('.index.json').read_text(encoding='utf-8'))
        self.assertTrue(any(p['images'] for p in index['pages']))
        self.assertTrue(any(p['tables'] for p in index['pages']))
        for path in [self.out] + [self.dir / p['file'] for p in index['pages']]:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('foreign.png', text)
            self.assertNotIn('![', text)
            for target in re.findall(r'\]\(([^)]+)\)', text):
                self.assertTrue((path.parent / unquote(target)).is_file(), (path, target))

    def test_quality_for_blank_page(self):
        source = self.dir / 'blank.pdf'
        doc = pymupdf.open()
        doc.new_page()
        doc.save(source)
        doc.close()
        converter.convert(source, self.out, extract_imgs=False)
        quality = json.loads(self.out.with_suffix('.quality.json').read_text(encoding='utf-8'))
        self.assertEqual(quality['status'], 'needs_review')
        self.assertIn('low_native_text', [v['code'] for v in quality['warnings']])

    def test_table_failures_are_reported(self):
        self.convert(extract_imgs=False)
        with patch.object(pymupdf.Page, 'find_tables', side_effect=RuntimeError('test extraction failure')):
            warnings = []
            with pymupdf.open(self.pdf) as doc:
                result = converter.extract_tables_for_page(doc[0], self.dir, self.dir, warnings)
        self.assertEqual(result, [])
        self.assertEqual(warnings[0]['code'], 'table_detection_failed')

    def test_suspicious_table_columns_are_flagged_not_deleted(self):
        class Table:
            bbox = (0, 0, 10, 10)
            def extract(self):
                return [['A', '', 'B'], ['1', None, '2']]
        class Finder:
            tables = [Table()]
        class Page:
            number = 0
            def find_tables(self):
                return Finder()
        warnings = []
        records = converter.extract_tables_for_page(Page(), self.dir, self.dir, warnings)
        self.assertEqual(records[0]['cols'], 3)
        self.assertEqual(warnings[0]['code'], 'table_empty_columns')
        self.assertIn('A,,B', Path(records[0]['path']).read_text(encoding='utf-8'))

    def test_reader_budgets_search_and_coverage(self):
        self.convert(extract_imgs=False)
        index = self.out.with_suffix('.index.json')
        result = read_excerpt(index, pages='2', max_chars=30)
        self.assertEqual(len(result['text']), 30)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['next_offset'], 30)
        self.assertEqual(read_excerpt(index, search='PAGE_2_UNIQUE')['matched_pages'], [2])
        self.assertEqual(read_excerpt(index, search='nonexistent')['matched_pages'], [])
        all_text, offset = '', 0
        while True:
            result = read_excerpt(index, offset=offset, max_chars=100)
            all_text += result['text']
            if result['next_offset'] is None:
                break
            offset = result['next_offset']
        self.assertIn('PAGE_1_UNIQUE', all_text)
        self.assertIn('PAGE_2_UNIQUE', all_text)
        self.assertEqual(all_text, read_excerpt(index, max_chars=100000)['text'])
        self.convert(pages='1', extract_imgs=False)
        with self.assertRaises(ValueError):
            read_excerpt(index, pages='2')

    def test_source_cannot_be_output(self):
        before = converter.digest(self.pdf)
        with self.assertRaises(ValueError):
            converter.convert(self.pdf, self.pdf, force=True)
        self.assertEqual(before, converter.digest(self.pdf))

    def test_page_line_ranges_and_portable_bundle(self):
        self.convert()
        index = json.loads(self.out.with_suffix('.index.json').read_text(encoding='utf-8'))
        lines = self.out.read_text(encoding='utf-8').splitlines()
        for page in index['pages']:
            excerpt = '\n'.join(lines[page['line_start']-1:page['line_end']])
            self.assertIn(f'PAGE_{page["page"]}_UNIQUE', excerpt)
            self.assertIn(f'PDF page: {page["page"]}', excerpt)
        moved = self.root / (self.dir.name + '-moved')
        shutil.copytree(self.dir, moved)
        result = read_excerpt(moved / 'paper.index.json', pages='2')
        self.assertIn('PAGE_2_UNIQUE', result['text'])
        for page in index['pages']:
            path = moved / page['file']
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                self.assertTrue((path.parent / unquote(target)).is_file())

    def test_scan_is_flagged_without_silent_ocr(self):
        scan = self.dir / 'scan.pdf'
        with pymupdf.open(self.pdf) as source:
            pix = source[0].get_pixmap()
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_image(page.rect, pixmap=pix)
            doc.save(scan)
            doc.close()
        converter.convert(scan, self.out)
        quality = json.loads(self.out.with_suffix('.quality.json').read_text(encoding='utf-8'))
        self.assertFalse(quality['ocr_enabled'])
        self.assertTrue(any(w['code'] == 'low_native_text' for w in quality['warnings']))

    def test_failure_does_not_replace_previous_markdown(self):
        self.convert()
        before = converter.digest(self.out)
        with patch('pymupdf4llm.to_markdown', side_effect=RuntimeError('conversion failed')):
            with self.assertRaises(RuntimeError):
                self.convert(force=True)
        self.assertEqual(before, converter.digest(self.out))
        self.assertEqual(self.convert()['status'], 'cached')

    def test_batch_handles_duplicate_names_and_failures(self):
        source = self.dir / 'batch'
        for folder in ('a', 'b'):
            (source / folder).mkdir(parents=True)
            shutil.copyfile(self.pdf, source / folder / 'same.pdf')
        (source / 'broken.pdf').write_text('not a PDF')
        result = subprocess.run([sys.executable, str(Path(converter.__file__)), str(source),
                                 '--output-dir', str(self.dir / 'converted'), '--recursive', '--no-images'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1, result.stderr)
        records = json.loads((self.dir / 'converted/batch-index.json').read_text(encoding='utf-8'))
        self.assertEqual(len([r for r in records if r['status'] == 'converted']), 2)
        self.assertEqual(len([r for r in records if r['status'] == 'failed']), 1)
        self.assertEqual(len({r['markdown'] for r in records if 'markdown' in r}), 2)


if __name__ == '__main__':
    unittest.main()
