#!/usr/bin/env python3
"""Read review rules and relation evidence directly from standalone LRML files.

Candidate annotations use the documented CNLR_REVIEW_META Comment profile;
these are application metadata, not standard executable LegalRuleML predicates.
Override direction is always read from the standard lrml:Override element.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re

from xml.etree import ElementTree as E

L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
MARKER = 'CNLR_REVIEW_META:'
R = '{http://ruleml.org/spec}'
RESOURCES = Path(__file__).resolve().parent / 'resources'


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


def resource(law):
    return RESOURCES / law / f'{law}_review.lrml'


def stats(document):
    return {'law': document.document['law'], 'rules': len(document.rules),
            'unmapped_rule_ids': sorted(k for k, r in document.rules.items() if not r['articles']),
            'draft_rows': document.document['draft_rows'],
            'standard_overrides': sum(1 for _ in document.root.iter(L + 'Override')),
            'relations': dict(collections.Counter(r['type'] for r in document.iter_relations(False))),
            'review_status': document.document['review_status']}


def rule_records(document):
    """Export all rules, preserving the actual RuleML body/head as XML."""
    for tag in ('ConstitutiveStatement', 'PrescriptiveStatement'):
        for element in document.root.iter(L + tag):
            key = element.get('key')
            if key not in document.rules:
                continue
            comment = element.find(L + 'Comment')
            yield dict(document.rules[key], key=key, statement_type=tag,
                       description=(comment.text or '').split(MARKER, 1)[0].strip() if comment is not None else '',
                       statement_xml=E.tostring(element, encoding='unicode'))


def validate(document, expected):
    """Check hashes, resource counts, XML IDs, rule sources and relation endpoints.

    This is an integrity check, not XSD validation or legal-content validation.
    """
    actual = stats(document)
    checks = []
    for field in ('rules', 'draft_rows', 'standard_overrides', 'review_status', 'relations', 'unmapped_rule_ids'):
        if actual[field] != expected[field]:
            raise ValueError(f'{document.path.name}: {field} differs from manifest')
        checks.append(field)
    digest = hashlib.sha256(document.path.read_bytes()).hexdigest()
    if digest != expected['sha256']:
        raise ValueError(f'{document.path.name}: SHA256 differs from manifest')
    checks.append('sha256')
    keys = [e.get('key') for e in document.root.iter() if e.get('key') is not None]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate XML key')
    known = set(keys)
    for e in document.root.iter():
        for name in ('keyref', 'over', 'under'):
            value = e.get(name)
            if value is not None and value.lstrip('#') not in known:
                raise ValueError(f'Unknown {name}: {value}')
    checks.append('xml_keys_and_references')
    if sum(1 for _ in document.root.iter(R + 'Rule')) != len(document.rules):
        raise ValueError('Some RuleML rules are absent from the metadata index')
    if any(r['review_status'] != 'pending_expert_review' for r in document.rules.values()):
        raise ValueError('Unexpected review status')
    # Reader construction checked source associations. Iteration verifies standard
    # Override direction and every grouped relation endpoint against that index.
    for _ in document.iter_relations():
        pass
    checks.extend(['rule_coverage', 'rule_sources_and_status', 'relation_endpoints_and_override_direction'])
    return {'law': actual['law'], 'ok': True, 'checks': checks, 'rules': actual['rules']}


def main():
    ap = argparse.ArgumentParser(description='CN-Onto: full civil/criminal review resources; Python standard library only.')
    commands = ap.add_subparsers(dest='command', required=True)
    stat = commands.add_parser('stats', help='Count full resources and typed relations')
    stat.add_argument('--law', choices=('civil', 'criminal', 'both'), default='both')
    article = commands.add_parser('article', help='Show rules and directed relation evidence for an article')
    article.add_argument('number', help='Article key, e.g. 1199 or criminal 17-1')
    article.add_argument('--law', choices=('civil', 'criminal'), default='civil')
    article.add_argument('--limit', type=int, default=5, help='Rules to display; 0 displays all')
    article.add_argument('--relations', choices=('override', 'all'), default='override')
    export = commands.add_parser('export', help='Export ALL rules as JSONL, including statement XML')
    export.add_argument('--law', choices=('civil', 'criminal'), default='civil')
    export.add_argument('--output', type=Path, required=True)
    commands.add_parser('validate', help='Check both full resources against the manifest (not XSD validation)')
    args = ap.parse_args()
    try:
        if args.command == 'validate':
            manifest = json.loads((RESOURCES / 'manifest.json').read_text(encoding='utf-8'))
            result = [validate(ReviewLRML(resource(law)), manifest['resources'][law])
                      for law in ('civil', 'criminal')]
        elif args.command == 'stats':
            laws = ('civil', 'criminal') if args.law == 'both' else (args.law,)
            result = [stats(ReviewLRML(resource(law))) for law in laws]
        else:
            document = ReviewLRML(resource(args.law))
            if args.command == 'export':
                if args.output.resolve() in {p.resolve() for p in RESOURCES.iterdir()}:
                    ap.error('Export output must not overwrite a packaged resource')
                with args.output.open('x', encoding='utf-8') as output:
                    for record in rule_records(document):
                        output.write(json.dumps(record, ensure_ascii=False) + '\n')
                result = {'law': args.law, 'rules_exported': len(document.rules), 'output': str(args.output)}
            else:
                if args.limit < 0:
                    ap.error('--limit must be non-negative')
                records = [r for r in rule_records(document) if args.number in r['articles']]
                if not records:
                    ap.error(f'No rules for article {args.number} in {args.law}')
                relations = [r for r in document.iter_relations()
                             if (args.relations == 'all' or r['type'] == 'override')
                             and args.number in r['from_articles'] + r['to_articles']]
                result = {'law': args.law, 'article': args.number, 'total_rules': len(records),
                          'rules': records if args.limit == 0 else records[:args.limit],
                          'display_limit': args.limit, 'relations': relations}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, E.ParseError) as error:
        ap.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
