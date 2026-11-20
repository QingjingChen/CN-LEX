#!/usr/bin/env python3
"""Build schema-valid LRML for both review workbooks, with embedded provenance.

Explicit source overrides use OverrideStatement. Heuristic relations and unresolved
records are comment-only FactualStatements, never executable override assertions.
The reader extracts retrieval relations from these LRML documents themselves.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from lxml import etree as E

HERE = Path(__file__).resolve().parent
L = 'http://docs.oasis-open.org/legalruleml/ns/v1.0/'
R = 'http://ruleml.org/spec'
MARKER = 'CNLR_REVIEW_META:'


def element(parent, name, text=None, **attrs):
    e = E.SubElement(parent, '{' + L + '}' + name, **attrs)
    if text is not None:
        e.text = text
    return e


def comment(parent, kind, record, note=''):
    element(parent, 'Comment', (note + '\n' if note else '') + MARKER +
            json.dumps({'kind': kind, 'record': record}, ensure_ascii=False))


def restore(rule):
    r = dict(rule)
    r['body'] = [tuple(b) if isinstance(b, list) else b for b in r['body']]
    r['heads'] = [tuple(h) if isinstance(h, list) else h for h in r['heads']]
    return r


def render(payload, source, out):
    law = payload['law']
    sys.path[:0] = [str(source / 'src/criminal'), str(source / 'src')]
    import graph2lrml as formatter
    import crim2lrml as criminal_formatter
    import civil_code
    import criminal_code
    root = E.Element('{' + L + '}LegalRuleML', nsmap={
        'lrml': L, 'ruleml': R, 'xs': 'http://www.w3.org/2001/XMLSchema',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'lrmlv': 'http://docs.oasis-open.org/legalruleml/ns/v1.0/metamodel#'})
    element(root, 'Prefix', key='cnv', refID=f'http://example.org/lexgo/{law}-vocab#')
    sources = element(root, 'LegalSources', key='review-legal-sources')
    raw_sources = sorted({s for v in payload['rules'].values() for s in v['rule']['srcs']})
    smap = {s: f'review-src-{i:05d}' for i, s in enumerate(raw_sources)}
    for s in raw_sources:
        m = re.fullmatch(r'art(\d+)(?:-(\d+))?(?:#(\d+))?', s)
        if m:
            n, suffix, para = m.groups()
            if law == 'civil':
                uri = f'/akn/cn/act/2020-05-28/civil-code/zho@/!main#art_{n}' + (f'__para_{suffix}' if suffix else '')
                text = civil_code.text_of(s)
            else:
                uri = f'/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main#art_{n}' + (f'_{suffix}' if suffix else '') + (f'__para_{para}' if para else '')
                text = criminal_code.text_of(s)
        else:
            uri, text = f'urn:lexgo:{law}:source:{s}', '原文未在本导出中提供；仅保留源规则中的引用标识：' + s
        ls = element(sources, 'LegalSource', key=smap[s], sameAs=uri)
        comment(ls, 'source', {'source_id': s, 'law': law}, text)
    authorities = element(root, 'Authorities', key='review-authorities')
    for auth in sorted({v['rule'].get('auth', 'npc') for v in payload['rules'].values()}):
        element(authorities, 'Authority', key='review-authority-' + auth)
    associations = element(root, 'Associations', key='review-associations')
    for key, v in payload['rules'].items():
        a = element(associations, 'Association')
        for s in v['rule']['srcs']:
            element(a, 'appliesSource', keyref='#' + smap[s])
        element(a, 'appliesAuthority', keyref='#review-authority-' + v['rule'].get('auth', 'npc'))
        element(a, 'appliesStrength', iri='lrmlv:' + v['rule'].get('strength', 'Defeasible'))
        element(a, 'toTarget', keyref='#' + key)
    statements = element(root, 'Statements', key='review-statements')
    status = element(statements, 'FactualStatement', key='review-document-metadata')
    comment(status, 'document', {k: payload[k] for k in ('law', 'review_status', 'draft_rows', 'source_repository', 'manifest')})
    for key, v in payload['rules'].items():
        r = restore(v['rule'])
        deontic = any(isinstance(h, tuple) for h in r['heads'])
        tag = 'PrescriptiveStatement' if deontic else 'ConstitutiveStatement'
        st = element(statements, tag, key=key)
        comment(st, 'rule', {'rule_id': key, 'articles': v['articles'],
                            'provenance': v['provenance'], 'review_status': 'pending_expert_review'}, r['note'])
        heads = [criminal_formatter.head_xml(h, key, i, r['note']) for i, h in enumerate(r['heads'])]
        if deontic and len(heads) == 1:
            head = '<lrml:SuborderList>' + heads[0] + '</lrml:SuborderList>'
        else:
            head = heads[0] if len(heads) == 1 else '<ruleml:And>' + ''.join(heads) + '</ruleml:And>'
        body = formatter.conj_xml(r['body'])
        xml = f'<ruleml:Rule xmlns:ruleml="{R}" xmlns:lrml="{L}" closure="universal" key=":{key}"><ruleml:if>{body}</ruleml:if><ruleml:then>{head}</ruleml:then></ruleml:Rule>'
        st.append(E.fromstring(xml.encode()))
    groups = {}
    for record in payload['relations']:
        if record['type'] == 'override':
            st = element(statements, 'OverrideStatement', key=record['id'])
            comment(st, 'relation', record)
            element(st, 'Override', over='#' + record['from_rule'], under='#' + record['to_rule'])
        else:
            sig = (record['type'], record['from_rule'], record.get('predicate'), record.get('condition_sign'))
            if sig not in groups:
                groups[sig] = {k: v for k, v in record.items() if k not in ('id', 'to_rule', 'to_articles')}
                groups[sig]['targets'] = []
            groups[sig]['targets'].append([record['id'], record['to_rule']])
    for i, record in enumerate(groups.values()):
        st = element(statements, 'FactualStatement', key=f'review-candidate-group-{i:06d}')
        comment(st, 'relation_group', record)
    for group in ('text_references', 'draft_annotations', 'unresolved_overrides'):
        for i, record in enumerate(payload[group]):
            st = element(statements, 'FactualStatement', key=f'review-{group}-{i:06d}')
            comment(st, group, record)
    schema = E.XMLSchema(E.parse(str(HERE.parent.parent / 'civil_graph/schema/lrml-compact.xsd')))
    schema.assertValid(root)
    keys = [e.get('key') for e in root.iter() if e.get('key')]
    assert len(keys) == len(set(keys)), 'Duplicate LRML keys'
    keyset = set(keys)
    for e in root.iter():
        for attr in ('keyref', 'over', 'under'):
            if e.get(attr, '').startswith('#'):
                assert e.get(attr)[1:] in keyset, (attr, e.get(attr))
    out.parent.mkdir(parents=True, exist_ok=True)
    E.ElementTree(root).write(str(out), encoding='UTF-8', xml_declaration=True, pretty_print=True)
    return {'law': law, 'path': str(out), 'rules': len(payload['rules']),
            'relations': payload['counts'], 'xsd_valid': True, 'keyrefs_valid': True,
            'sha256': hashlib.sha256(out.read_bytes()).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=Path.home() / 'codebook/LexReAct')
    ap.add_argument('--law', choices=('civil', 'criminal', 'both'), default='both')
    args = ap.parse_args()
    report = []
    for law in ('civil', 'criminal') if args.law == 'both' else (args.law,):
        path = HERE / 'data' / ('review_relations.json' if law == 'civil' else 'criminal_review_relations.json')
        subprocess.run([sys.executable, str(HERE / 'export_review_relations.py'), '--source', str(args.source),
                        '--law', law, '--out', str(path)], check=True)
        payload = json.loads(path.read_text())
        report.append(render(payload, args.source, HERE.parent / 'lrml' / f'{law}_review.lrml'))
    (HERE / 'results/review_lrml_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
