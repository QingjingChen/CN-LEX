import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cn_lex as C


class ResourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((C.RESOURCES / 'manifest.json').read_text(encoding='utf-8'))
        cls.docs = {law: C.ReviewLRML(C.resource(law)) for law in ('civil', 'criminal')}

    def test_all_rules_sources_and_relations(self):
        for law, document in self.docs.items():
            with self.subTest(law=law):
                self.assertTrue(C.validate(document, self.manifest['resources'][law])['ok'])
                records = list(C.rule_records(document))
                self.assertEqual(len(records), self.manifest['resources'][law]['rules'])
                self.assertTrue(all(record['statement_xml'] for record in records))

    def test_civil_1199_1201_override(self):
        matches = [r for r in self.docs['civil'].iter_relations(False)
                   if r['type'] == 'override' and '1201' in r['from_articles']
                   and '1199' in r['to_articles']]
        self.assertTrue(matches)

    def test_tampered_direction_is_rejected(self):
        document = copy.deepcopy(self.docs['civil'])
        element = next(document.root.iter(C.L + 'Override'))
        over, under = element.get('over'), element.get('under')
        element.set('over', under)
        element.set('under', over)
        with self.assertRaisesRegex(ValueError, 'direction'):
            list(document.iter_relations(False))

    def test_packaged_metadata_has_no_home_paths(self):
        for law in self.docs:
            self.assertNotIn(b'/Users/', C.resource(law).read_bytes())


if __name__ == '__main__':
    unittest.main()
