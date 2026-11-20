"""End-to-end source -> LRML -> retrieval integrity checks for both laws."""
import collections
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as E

from review_lrml_reader import ReviewLRML, article_neighbours, L

HERE = Path(__file__).resolve().parent


def signature(records):
    digest = 0
    count = 0
    for r in records:
        projection = [r['type'], r.get('id'), r.get('from_rule'), r.get('to_rule'), r.get('predicate'),
                      sorted(map(str, r['from_articles'])), sorted(map(str, r['to_articles']))]
        digest = (digest + int.from_bytes(hashlib.sha256(json.dumps(projection).encode()).digest(), 'big')) % (1 << 256)
        count += 1
    return count, digest


class RoundTripTest(unittest.TestCase):
    def test_both_laws_preserve_rules_relations_and_sources(self):
        for law in ('civil', 'criminal'):
            with self.subTest(law=law):
                p = HERE / 'data' / ('review_relations.json' if law == 'civil' else 'criminal_review_relations.json')
                source = json.loads(p.read_text())
                document = ReviewLRML(HERE.parent / 'lrml' / f'{law}_review.lrml')
                self.assertEqual(set(source['rules']), set(document.rules))
                for k, r in source['rules'].items():
                    self.assertEqual(set(map(str, r['articles'])), set(document.rules[k]['articles']))
                    self.assertEqual(document.rules[k]['review_status'], 'pending_expert_review')
                    self.assertEqual(document.rules[k]['provenance'], r['provenance'])
                self.assertEqual(signature(source['relations']), signature(document.iter_relations(False)))
                self.assertEqual(dict(collections.Counter(r['type'] for r in document.iter_relations(False))), source['counts'])

    def test_school_priority_is_read_from_lrml(self):
        graph = article_neighbours(HERE.parent / 'lrml/civil_review.lrml', {'override'})
        self.assertIn('1201', graph['1199'])

    def test_override_metadata_cannot_silently_reverse_standard_direction(self):
        tree = E.parse(HERE.parent / 'lrml/civil_review.lrml')
        override = next(tree.getroot().iter(L + 'Override'))
        a, b = override.get('over'), override.get('under')
        override.set('over', b)
        override.set('under', a)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'tampered.lrml'
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'direction'):
                list(ReviewLRML(path).iter_relations())


if __name__ == '__main__':
    unittest.main()
