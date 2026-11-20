#!/usr/bin/env python3
"""Criminal statute retrieval: question/options only; explanation citations are labels only.

Reuse the original 883-question embeddings to avoid any LLM call. Select the
citation-labelled subset, split 30/70 seed 0, and tune weights on development only.
"""
import collections
import hashlib
import json
from pathlib import Path
import random
import sys
from xml.etree import ElementTree as ET

import numpy as np
from retrieval_lib import BM25, embed, HERE, mean, metrics, minmax, randomization
from review_lrml_reader import article_neighbours, L

P = Path(HERE)
sys.path.insert(0, str(P.parent.parent / 'civil_graph'))
from civil_code import cn2int


def main():
    law = json.loads((P.parent.parent / 'crim_graph/law/criminal_law_2023.json').read_text())
    qa = [json.loads(s) for s in (P.parent / 'data/fakao_criminal_qa.jsonl').read_text().splitlines()]
    articles = {a: f"《刑法》{v['label']}：" + ''.join(v['paras']) for a, v in law.items()}
    texts = {q['id']: f"{q['question']}\nA. {q['A']}\nB. {q['B']}\nC. {q['C']}\nD. {q['D']}" for q in qa}
    queries, dropped = [], []
    for q in qa:
        gold = set()
        for a in q['criminal_articles']:
            parts = a.split('之')
            parts = [s if s.isdigit() else str(cn2int(s)) for s in parts]
            key = '-'.join(parts)
            if key in articles:
                gold.add(key)
            else:
                dropped.append({'id': q['id'], 'citation': a})
        if gold:
            queries.append({'qid': q['id'], 'gold': sorted(gold)})
    queries.sort(key=lambda q: q['qid'])
    dev_ids = {q['qid'] for q in random.Random(0).sample(queries, round(.3 * len(queries)))}
    dev = [q for q in queries if q['qid'] in dev_ids]
    test = [q for q in queries if q['qid'] not in dev_ids]
    # These dictionaries exactly match the cached QA context embedding inputs.
    aids, A = embed(articles, max_len=1024, bs=16)
    qids, X = embed(texts, max_len=1024, bs=16)
    dense = {k: dict(zip(aids, map(float, A @ X[i]))) for i, k in enumerate(qids)}
    path = P.parent / 'lrml/criminal_review.lrml'
    legacy = collections.defaultdict(dict)
    root = ET.parse(P.parent.parent / 'crim_graph/crim_graph.lrml').getroot()
    source_arts = {}
    for e in root.iter(L + 'LegalSource'):
        uri = e.get('sameAs', '')
        import re
        m = re.search(r'#art_(\d+(?:_\d+)?)(?:__para_\d+)?$', uri)
        if m:
            source_arts[e.get('key')] = m.group(1).replace('_', '-')
    rule_arts = collections.defaultdict(set)
    for e in root.iter(L + 'Association'):
        arts = {source_arts[s.get('keyref', '').lstrip('#')] for s in e.findall(L + 'appliesSource') if s.get('keyref', '').lstrip('#') in source_arts}
        for t in e.findall(L + 'toTarget'):
            rule_arts[t.get('keyref').lstrip('#')].update(arts)
    for e in root.iter(L + 'Override'):
        for a in rule_arts[e.get('over').lstrip('#')]:
            for b in rule_arts[e.get('under').lstrip('#')]:
                if a != b and a in articles and b in articles:
                    legacy[a][b] = legacy[b][a] = 1
    graphs = {'legacy_override': legacy,
              'review_override': article_neighbours(path, {'override'}, set(articles)),
              'review_all': article_neighbours(path, valid_articles=set(articles))}
    bm = BM25(articles)

    def evaluate(fn, subset):
        per = {}
        for q in subset:
            s = fn(q['qid']); gold = dict.fromkeys(q['gold'], 1)
            m = metrics(s, gold, ks_r=(5, 10, 20), ks_n=(10,))
            m['Path@10'] = float(set(gold) <= set(sorted(s, key=lambda a: -s[a])[:10]))
            per[q['qid']] = m
        return per

    per = {'Dense': evaluate(lambda k: dense[k], test), 'BM25': evaluate(lambda k: bm.score(texts[k]), test)}
    rankings = {q['qid']: {'gold': q['gold'], 'Dense': sorted(dense[q['qid']], key=dense[q['qid']].get, reverse=True)[:10]} for q in test}
    weights, counts = {}, {}
    for name, graph in graphs.items():
        for pool in ('top20', 'expansion'):
            label = f'{name}/{pool}'
            feat = {}
            for q in queries:
                k = q['qid']; s = dense[k]; d = minmax(s)
                order = sorted(s, key=lambda a: -s[a]); seeds = order[:5]
                candidates = set(order[:20])
                if pool == 'expansion':
                    candidates.update(a for b in seeds for a in graph.get(b, {}))
                norm = minmax({a: sum(d[b] for b in seeds if a != b and a in graph.get(b, {})) for a in sorted(candidates)})
                feat[k] = {a: (d[a], norm[a]) for a in sorted(candidates)}

            def score(k, w):
                if w == 0:
                    return dense[k]
                s = {a: d + w * n for a, (d, n) in feat[k].items()}
                floor = min(s.values()) - 1
                return {a: s.get(a, floor + v) for a, v in dense[k].items()}

            w = max((0, .05, .1, .2, .3, .5, .75, 1.), key=lambda v: (mean(evaluate(lambda k: score(k, v), dev))['NDCG@10'], -v))
            weights[label] = w
            per[label] = evaluate(lambda k: score(k, w), test)
            counts[label] = float(np.mean([len(feat[q['qid']]) for q in test]))
            for q in test:
                s = score(q['qid'], w)
                rankings[q['qid']][label] = sorted(s, key=lambda a: -s[a])[:10]
    multi = {q['qid'] for q in test if len(q['gold']) >= 2}
    result = {'n': len(queries), 'n_test_multi': len(multi), 'n_articles': len(articles),
              'split': {'dev': sorted(dev_ids), 'test': [q['qid'] for q in test]},
              'query_fields': ['question', 'A', 'B', 'C', 'D'], 'gold_only_field': 'criminal_articles',
              'dropped_citations': dropped, 'review_status': 'pending_expert_review',
              'relation_source': str(path), 'relation_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'graph_pairs': {n: sum(map(len, g.values())) // 2 for n, g in graphs.items()},
              'weights_on_dev': weights, 'mean_candidate_count': counts,
              'test': {n: mean(v) for n, v in per.items()},
              'test_multi': {n: mean({k: v for k, v in p.items() if k in multi}) for n, p in per.items()},
              'per_query': per, 'rankings': rankings,
              'sig': {n: {m: randomization(per['Dense'], p, m) for m in ('R@10', 'NDCG@10', 'Path@10')}
                      for n, p in per.items() if n != 'Dense'},
              'limitations': ['Explanation citations are incomplete relevance labels, used only for evaluation',
                              'Questions span 2002-2024 but statutes use the 2023 consolidated text',
                              'All new relations await expert review; name matches are not legal proof',
                              'No LLM answering or rule-engine inference is evaluated']}
    out = P / 'results/criminal_review_retrieval.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('rankings', 'per_query', 'split')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
