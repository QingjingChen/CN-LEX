"""Regression checks for the pending-review relation adapter."""
import json
from pathlib import Path
import tempfile
import unittest

from civil_review_retrieval import review_neighbours


class ReviewRelationsTest(unittest.TestCase):
    def test_filter_invalid_self_and_reciprocal_links(self):
        records = [
            {'type': 'override', 'from_articles': [1199], 'to_articles': [1201]},
            {'type': 'depends_candidate', 'from_articles': [1199], 'to_articles': [1200]},
            {'type': 'override', 'from_articles': [1199], 'to_articles': [1199, 9999]},
        ]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'relations.json'
            f.write_text(json.dumps({'relations': records, 'text_references': [
                {'type': 'explicit_text_reference', 'from_articles': [1199], 'to_articles': []}]}))
            n = review_neighbours(f, {'override'})
            self.assertEqual(dict(n), {'1199': {'1201': 1}, '1201': {'1199': 1}})
            self.assertIn('1200', review_neighbours(f)['1199'])

    def test_export_referential_integrity_and_status(self):
        path = Path(__file__).parent / 'data/review_relations.json'
        if not path.exists():
            self.skipTest('Run export_review_relations.py first')
        data = json.loads(path.read_text())
        self.assertGreater(data['draft_rows'], 0)
        for edge in data['relations']:
            self.assertEqual(edge['review_status'], 'pending_expert_review')
            for side in ('from', 'to'):
                self.assertEqual(edge[side + '_articles'], data['rules'][edge[side + '_rule']]['articles'])
        for graph in (review_neighbours(path), review_neighbours(path, {'override'})):
            for a, neighbours in graph.items():
                self.assertNotIn(a, neighbours)
                for b in neighbours:
                    self.assertIn(a, graph[b])


if __name__ == '__main__':
    unittest.main()
