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
