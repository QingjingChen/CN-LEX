"""Akoma Ntoso layer: structure, unique eIds, schema validity, and resolution of every AKN URI used by the
LegalRuleML and RDF resources."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AKN = '{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}'
DOCS = {
    '/akn/cn/act/2020-05-28/civil-code/zho@/!main': ROOT / 'resources/akn/civil-code.akn.xml',
    '/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main': ROOT / 'resources/akn/criminal-law.akn.xml',
}
EXPECTED = {'civil-code.akn.xml': dict(article=1260, chapter=84, book=8, part=8),
            'criminal-law.akn.xml': dict(article=505, chapter=15, book=3, part=0)}


class AknTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {expr: ET.parse(path) for expr, path in DOCS.items()}

    def test_structure_and_unique_eids(self):
        for expr, tree in self.trees.items():
            name = DOCS[expr].name
            with self.subTest(doc=name):
                for tag, n in EXPECTED[name].items():
                    self.assertEqual(len(list(tree.iter(AKN + tag))), n, tag)
                eids = [e.get('eId') for e in tree.iter() if e.get('eId')]
                self.assertEqual(len(eids), len(set(eids)))
                this = tree.find(f'.//{AKN}FRBRExpression/{AKN}FRBRthis').get('value')
                self.assertEqual(this, expr)

    def test_every_akn_uri_resolves(self):
        ids = {expr: {e.get('eId') for e in tree.iter() if e.get('eId')} for expr, tree in self.trees.items()}
        files = sorted((ROOT / 'resources').glob('*/*.lrml')) + sorted((ROOT / 'resources/rdf').glob('*.ttl'))
        for f in files:
            uris = set(re.findall(r'(/akn/cn/act/[^"<>\s#]+)#([A-Za-z0-9_]+)', f.read_text(encoding='utf-8')))
            with self.subTest(file=f.name):
                self.assertTrue(uris)
                missing = [u for u in uris if u[1] not in ids.get(u[0], set())]
                self.assertEqual(missing, [])

    def test_no_part_heading_inside_statutory_text(self):
        for f in sorted((ROOT / 'resources').glob('*/*.lrml')) + sorted((ROOT / 'resources/rdf').glob('*.ttl')):
            text = f.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'\n\n第[一二三四五]分编　[^<"]*(</lrml:Comment>|""")', text), f.name)

    def test_passive_modifications(self):
        tree = ET.parse(DOCS['/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main'])
        ids = {e.get('eId') for e in tree.iter() if e.get('eId')}
        mods = list(tree.iter(AKN + 'textualMod'))
        self.assertEqual(len(mods), 367)
        self.assertEqual(len(list(tree.iter(AKN + 'passiveRef'))), 14)
        for m in mods:
            for tag in ('source', 'destination'):
                self.assertIn(m.find(AKN + tag).get('href')[1:], ids, m.get('eId'))
            self.assertIn(m.find(AKN + 'force').get('period')[1:], ids, m.get('eId'))
            self.assertTrue(m.find(AKN + 'old') is not None or m.find(AKN + 'new') is not None, m.get('eId'))
        periods = {e.get('period')[1:] for e in tree.iter() if e.get('period')}
        self.assertTrue(periods <= ids)

    def test_timeline_reproduces_official_text(self):
        import json
        tl = json.loads((ROOT / 'data/statutes/criminal_timeline.json').read_text(encoding='utf-8'))
        self.assertEqual(tl['manual_review'], [])
        self.assertEqual(tl['final_paragraph_split_differences'], [])
        residual = {d['article'] for d in tl['final_content_differences'] + tl['never_amended_articles_differing_from_official']}
        self.assertEqual(residual, {'art_187', 'art_308_1', 'art_367'})   # explained in resources/akn/criminal-law-timeline.md

    def test_schema_validity(self):
        try:
            from lxml import etree
        except ImportError:
            self.skipTest('lxml not installed')
        xsd = etree.XMLSchema(etree.parse(str(ROOT / 'resources/schema/akn/akomantoso30.xsd')))
        for path in DOCS.values():
            with self.subTest(doc=path.name):
                self.assertTrue(xsd.validate(etree.parse(str(path))), str(xsd.error_log.last_error))


if __name__ == '__main__':
    unittest.main()
