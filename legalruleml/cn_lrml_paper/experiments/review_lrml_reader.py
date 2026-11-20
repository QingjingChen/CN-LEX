#!/usr/bin/env python3
"""Read review rules and relation evidence directly from standalone LRML files.

Candidate annotations use the documented CNLR_REVIEW_META Comment profile;
these are application metadata, not standard executable LegalRuleML predicates.
Override direction is always read from the standard lrml:Override element.
"""
import argparse
import collections
import json
from pathlib import Path
import re

from xml.etree import ElementTree as E

L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
MARKER = 'CNLR_REVIEW_META:'


def metadata(element):
    c = element.find(L + 'Comment')
    if c is not None and c.text and MARKER in c.text:
        return json.loads(c.text.split(MARKER, 1)[1])
    return None


class ReviewLRML:
    def __init__(self, path):
        self.path = Path(path)
        self.root = E.parse(str(path)).getroot()
        self.rules = {}
        self.document = None
        sources = {}
        for e in self.root.iter(L + 'LegalSource'):
            uri = e.get('sameAs', '')
            m = re.search(r'#art_(\d+(?:_\d+)?)(?:__para_\d+)?$', uri)
            if m:
                sources[e.get('key')] = m.group(1).replace('_', '-')
        associations = collections.defaultdict(set)
        for e in self.root.iter(L + 'Association'):
            arts = {sources[s.get('keyref', '').lstrip('#')] for s in e.findall(L + 'appliesSource')
                    if s.get('keyref', '').lstrip('#') in sources}
            for target in e.findall(L + 'toTarget'):
                associations[target.get('keyref').lstrip('#')].update(arts)
        for tag in ('ConstitutiveStatement', 'PrescriptiveStatement'):
            for e in self.root.iter(L + tag):
                m = metadata(e)
                if m and m['kind'] == 'rule':
                    r = m['record']
                    # Cross-check embedded metadata against actual LegalSource associations.
                    actual = associations[e.get('key')]
                    if actual != {str(a) for a in r['articles']}:
                        raise ValueError(f'Source mapping mismatch: {e.get("key")}')
                    self.rules[e.get('key')] = dict(r, articles=sorted(actual))
        for e in self.root.iter(L + 'FactualStatement'):
            m = metadata(e)
            if m and m['kind'] == 'document':
                self.document = m['record']
                break
        if self.document is None:
            raise ValueError('Missing review document metadata')

    def iter_relations(self, include_text=True):
        for e in self.root.iter(L + 'OverrideStatement'):
            override = e.find(L + 'Override')
            a, b = override.get('over').lstrip('#'), override.get('under').lstrip('#')
            m = metadata(e)
            r = dict(m['record']) if m else {'type': 'override', 'id': e.get('key')}
            if r.get('from_rule', a) != a or r.get('to_rule', b) != b:
                raise ValueError('Override direction differs from embedded metadata')
            yield dict(r, from_rule=a, to_rule=b, from_articles=self.rules[a]['articles'],
                       to_articles=self.rules[b]['articles'])
        for e in self.root.iter(L + 'FactualStatement'):
            m = metadata(e)
            if not m:
                continue
            kind, r = m['kind'], m['record']
            if kind == 'relation_group':
                base = {k: v for k, v in r.items() if k != 'targets'}
                for rid, target in r['targets']:
                    yield dict(base, id=rid, to_rule=target,
                               from_articles=self.rules[r['from_rule']]['articles'],
                               to_articles=self.rules[target]['articles'])
            elif kind == 'text_references' and include_text:
                yield r


def article_neighbours(path, types=None, valid_articles=None):
    document = ReviewLRML(path)
    graph = collections.defaultdict(dict)
    for r in document.iter_relations():
        if types is not None and r['type'] not in types:
            continue
        for a in r['from_articles']:
            for b in r['to_articles']:
                a, b = str(a), str(b)
                if a != b and (valid_articles is None or a in valid_articles and b in valid_articles):
                    graph[a][b] = graph[b][a] = 1
    return graph


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path', type=Path)
    ap.add_argument('--article', help='Article key, e.g. 1199 or 17-1')
    ap.add_argument('--overrides-only', action='store_true')
    args = ap.parse_args()
    d = ReviewLRML(args.path)
    counts = collections.Counter(r['type'] for r in d.iter_relations(False))
    result = {'law': d.document['law'], 'rules': len(d.rules), 'relations': dict(counts),
              'review_status': d.document['review_status']}
    if args.article:
        g = article_neighbours(args.path, {'override'} if args.overrides_only else None)
        result['article'] = args.article
        result['neighbours'] = sorted(g.get(args.article, {}))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
