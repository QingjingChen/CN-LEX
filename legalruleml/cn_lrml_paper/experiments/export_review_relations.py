#!/usr/bin/env python3
"""Export the rule set used by build_review_all, without editing the review workbook.

Predicate matches reproduce the workbook's structural heuristic, not proven legal
dependencies. All exported relations remain pending expert review.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=Path.home() / 'codebook/LexReAct')
    ap.add_argument('--law', choices=('civil', 'criminal'), default='civil')
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    a.out = a.out or HERE / ('data/review_relations.json' if a.law == 'civil' else 'data/criminal_review_relations.json')
    sys.path[:0] = [str(a.source / 'src/codebook'), str(a.source / 'src')]
    import build_review_all as review

    if a.law == 'criminal':
        sys.path.insert(0, str(a.source / 'src/criminal'))
        import build_review_criminal as criminal
        rules = {r['key']: r for _, rs in criminal.CR.MODULES.values() for r in rs}
        overrides = list(criminal.CR.OVERRIDES)
        draft_dir = criminal.DRAFTS
        article_key = criminal.art_key
        article_ids = set(criminal.K.articles())
    else:
        rules, overrides = review.all_rules()
        draft_dir = review.DRAFTS
        article_key = lambda s: str(review.B.art_of(s)) if s.startswith('art') else None
        article_ids = {str(n) for n in range(1, 1261)}
    owners = {k: {'kind': 'existing_formal_rule'} for k in rules}
    drafts = review.load_drafts(draft_dir)
    annotations = []
    for rid, d in drafts.items():
        for field in ('priority', 'exceptions', 'distinguish'):
            for item in d.get('nl', {}).get(field, []):
                annotations.append({'row_id': rid, 'field': field, 'annotation': item,
                                    'model': d.get('model'), 'review_status': 'pending_expert_review',
                                    'retrieval_use': 'annotation_only; no edge inferred from free text'})
        for r in d['rules']:
            rules[r['key']] = review.draft_rule(r)
            owners[r['key']] = {'kind': 'draft', 'row_id': rid, 'model': d.get('model'),
                                'risk_notes': review.draft_risk(rid, d, [])}
        overrides.extend(tuple(o) for o in d.get('overrides', []))
    arts = {k: sorted({article_key(s) for s in r['srcs'] if article_key(s)})
            for k, r in rules.items()}
    assert all(n in article_ids for ns in arts.values() for n in ns)
    relations, seen = [], set()

    def add(kind, source, target, **extra):
        sig = (kind, source, target, extra.get('predicate'), extra.get('reason'))
        if sig in seen:
            return
        seen.add(sig)
        relations.append({'id': f'review-rel-{len(relations):07d}', 'type': kind,
                          'from_rule': source, 'to_rule': target,
                          'from_articles': arts[source], 'to_articles': arts[target],
                          'review_status': 'pending_expert_review', **extra})

    defs = collections.defaultdict(set)
    for k, r in rules.items():
        for h in r['heads']:
            for sign, p in review.B.preds(h):
                defs[p].add(k)
    for k, r in rules.items():
        for b in r['body']:
            for sign, p in review.B.preds(b):
                for d in sorted(defs.get(p, ())):
                    if d != k and set(arts[d]) != set(arts[k]):
                        add({'': 'depends_candidate', '~': 'exception_candidate',
                             '-': 'negative_condition_candidate'}[sign], k, d,
                            predicate=p, condition_sign=sign,
                            derivation='workbook_predicate_name_match',
                            limitation='Name match only; polarity, arguments and OR alternatives require review')
    unresolved = []
    for over, under, why in overrides:
        if over in rules and under in rules:
            add('override', over, under, reason=why, derivation='source_rule_override')
        else:
            unresolved.append([over, under, why])
    manifest = []
    for p in sorted(draft_dir.rglob('*.json')):
        manifest.append({'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    text_references = []
    for n in sorted(article_ids):
        text = (''.join(review.CC.paragraphs(int(n))) if a.law == 'civil'
                else ''.join(criminal.K.articles()[n]['paras']))
        for m in (review.XREF if a.law == 'civil' else criminal.XREF).finditer(text):
            target = str(review.CC.cn2int(m.group(1))) if m.group(1) else None
            if a.law == 'criminal' and target and m.group(2):
                target += '-' + str(review.CC.cn2int(m.group(2)[1:]))
            text_references.append({'from_articles': [n],
                                    'to_articles': [target] if target in article_ids else [],
                                    'type': 'explicit_text_reference', 'text': m.group(0),
                                    'resolution': 'article' if target else 'unresolved_scope',
                                    'review_status': 'pending_expert_review'})
    output = {'schema_version': 2, 'law': a.law, 'review_status': 'pending_expert_review',
              'source_repository': str(a.source.resolve()),
              'selection': 'build_review_all.load_drafts: root > claude-agent > deepseek; same suffixing',
              'manifest': manifest, 'draft_rows': len(drafts), 'rules': {
                  k: {'articles': arts[k], 'provenance': owners[k], 'rule': r}
                  for k, r in rules.items()}, 'relations': relations,
              'unresolved_overrides': unresolved, 'text_references': text_references,
              'draft_annotations': annotations,
              'counts': dict(collections.Counter(r['type'] for r in relations))}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({'draft_rows': len(drafts), 'rules': len(rules),
                      'counts': output['counts'], 'unresolved_overrides': len(unresolved)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
