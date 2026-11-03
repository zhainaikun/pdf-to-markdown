import sys, unittest, tempfile, json, subprocess, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import pymupdf
import pdf_to_md as converter
from text_cleanup import repair_spacing, suspect_words, split_references, clean_page
from read_md import read_excerpt, render_excerpt

class V2Tests(unittest.TestCase):
    def test_reference_split_preserves_following_appendix(self):
        text = 'Results\n123.4 value\n## **References**\nSmith 2020\n## Appendix A\nMore results\n'
        body, refs, active = split_references(text)
        self.assertIn('123.4',body)
        self.assertIn('More results',body)
        self.assertNotIn('Smith',body)
        self.assertIn('Smith',refs)
        self.assertFalse(active)
        self.assertEqual(split_references('References are discussed here.\n')[0], 'References are discussed here.\n')

    def test_duplicate_caption_and_optional_cleanup(self):
        caption='Figure 1. Important unique finding.'
        text=f'Journal header\n\n{caption}\n\nBody finding\n\n{caption}'
        clean, removed=clean_page(text,{'Journal header'},set(),True,True)
        self.assertEqual(clean.count(caption),1)
        self.assertIn('Body finding',clean)
        self.assertEqual(len(removed),2)
        self.assertEqual(clean_page(text,set(),set())[0],text)

    def test_geometry_spacing_and_warning(self):
        class Page:
            def get_text(self, mode):
                chars=[]; x=0
                for word in ('detection','of','indoxacarb','resistance'):
                    for c in word:
                        chars.append({'c':c,'bbox':(x,0,x+5,10)}); x+=5
                    x+=1.3
                return {'blocks':[{'lines':[{'dir':(1,0),'spans':[{'size':10,'chars':chars}]}]}]}
        raw='**detectionofindoxacarbresistance** F1845Y 1794'
        text, repairs=repair_spacing(raw,Page())
        self.assertEqual(text,'**detection of indoxacarb resistance** F1845Y 1794')
        self.assertTrue(repairs)
        self.assertTrue(suspect_words(raw))
        self.assertFalse(suspect_words(text))
        self.assertFalse(suspect_words('ATTCTACAAATCATAAAGATATTGG'))

    def test_sidecar_cache_and_plain_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); pdf=root/'a.pdf'; out=root/'paper.md'
            doc=pymupdf.open(); p=doc.new_page()
            p.insert_text((72,72),'Research results with sufficient text to test extraction.')
            p.insert_text((72,130),'References',fontsize=18)
            p.insert_text((72,160),'Smith 2020. A reference title.')
            doc.save(pdf); doc.close()
            converter.convert(pdf,out,extract_imgs=False,extract_tables=False)
            refs=out.with_suffix('.references.md')
            self.assertIn('Smith',refs.read_text(encoding='utf-8'))
            self.assertNotIn('Smith',out.read_text(encoding='utf-8'))
            self.assertEqual(converter.convert(pdf,out,extract_imgs=False,extract_tables=False)['status'],'cached')
            refs.write_text('corrupt',encoding='utf-8')
            self.assertEqual(converter.convert(pdf,out,extract_imgs=False,extract_tables=False)['status'],'converted')
            index=out.with_suffix('.index.json')
            result=read_excerpt(index,pages='1',max_chars=30)
            self.assertIn('[continue --offset 30]',render_excerpt(result))
            cmd=[sys.executable,str(Path(converter.__file__).with_name('read_md.py')),str(index),'--pages','1']
            cli=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',check=True)
            self.assertEqual(cli.stdout,render_excerpt(read_excerpt(index,pages='1'))+'\n')
            self.assertNotIn('matched_pages',cli.stdout)
            converter.convert(pdf,out,extract_imgs=False,extract_tables=False,references='inline')
            self.assertIn('Smith',out.read_text(encoding='utf-8'))

if __name__=='__main__':
    unittest.main()
