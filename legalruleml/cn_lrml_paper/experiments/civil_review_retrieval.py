#!/usr/bin/env python3
"""Controlled retrieval evaluation of pending review-workbook relations.

All methods reuse Dense(text), fixed Top20/Top5 seeds and the historical split.
Relation types/directions are retained in export; retrieval uses undirected binary
adjacency, without claiming that an override has been legally applied.
"""
import argparse
import collections
import json
from pathlib import Path
import random

import numpy as np
import civil_run as CR
import civil_full_run as CF
from retrieval_lib import embed, mean, metrics, minmax, randomization, HERE


def review_neighbours(path, types=None):
    if Path(path).suffix == '.lrml':
        from review_lrml_reader import article_neighbours
        return article_neighbours(path, types, set(CR.ARTS))
    data = json.loads(Path(path).read_text())
    edges = collections.defaultdict(dict)
    for r in data['relations'] + data.get('text_references', []):
        if types is not None and r['type'] not in types:
            continue
        for a in r['from_articles']:
            for b in r['to_articles']:
                a, b = str(a), str(b)
                if a != b and a in CR.ARTS and b in CR.ARTS:
                    edges[a][b] = edges[b][a] = 1
    return edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--relations', default=str(Path(HERE).parent / 'lrml/civil_review.lrml'))
    ap.add_argument('--out', default=str(Path(HERE) / 'results/civil_review_retrieval.json'))
    args = ap.parse_args()
    qs = sorted(CR.Q, key=lambda q: q['qid'])
    dev_ids = {q['qid'] for q in random.Random(0).sample(qs, round(.3 * len(qs)))}
    dev = [q for q in qs if q['qid'] in dev_ids]
    test = [q for q in qs if q['qid'] not in dev_ids]
    aids, A = embed({a: v['text'] for a, v in CR.ARTS.items()}, max_len=1024, bs=16)
    qids, X = embed({str(q['qid']): q['text'] for q in CR.Q}, max_len=1024, bs=16)
    scores = X @ A.T
    dense = {k: dict(zip(aids, map(float, scores[i]))) for i, k in enumerate(qids)}
    old = CF.merge(CR.neighbours(['override', 'exception', 'depends']), CF.card_edges())
    new = review_neighbours(args.relations)
    override = review_neighbours(args.relations, {'override'})
    graphs = {'old': old, 'review_override': override, 'review_all': new,
              'old+review': CF.merge(old, new)}
    features, pools = {}, {}
    for name, graph in graphs.items():
        for qid, s in dense.items():
            order = sorted(s, key=lambda a: -s[a]); seeds = order[:5]
            # One fixed normalisation across all methods and candidate pools.
            d = minmax(s)
            for pool in ('top20', 'expansion'):
                candidates = set(order[:20])
                if pool == 'expansion':
                    candidates.update(a for b in seeds for a in graph.get(b, {}))
                cands = sorted(candidates)
                norm = {a: sum(d[b] for b in seeds if a != b and a in graph.get(b, {})) for a in cands}
                norm = minmax(norm)
                features[name, qid, pool] = {a: (d[a], norm[a]) for a in cands}
                pools[name, qid, pool] = len(cands)

    def run(name, pool, weight, qid):
        f = features[name, qid, pool]
        s = {a: d + weight * n for a, (d, n) in f.items()}
        floor = min(s.values()) - 1
        return {a: s.get(a, floor + v) for a, v in dense[qid].items()}

    def evaluate(fn, subset):
        per = {}
        for q in subset:
            k = str(q['qid']); s = fn(k); gold = {str(a): 1 for a in q['gold']}
            m = metrics(s, gold, ks_r=(5, 10, 20), ks_n=(10,))
            top10 = set(sorted(s, key=lambda a: -s[a])[:10])
            m['Path@10'] = float(set(gold) <= top10)
            per[k] = m
        return per

    per = {'Dense': evaluate(lambda k: dense[k], test)}
    chosen, candidate_counts = {}, {}
    for name in graphs:
        for pool in ('top20', 'expansion'):
            label = f'{name}/{pool}'
            grid = (0, .05, .1, .2, .3, .5, .75, 1.)
            weight = max(grid, key=lambda w: (mean(evaluate(lambda k: run(name, pool, w, k), dev))['NDCG@10'], -w))
            chosen[label] = weight
            per[label] = evaluate(lambda k: run(name, pool, weight, k), test)
            candidate_counts[label] = float(np.mean([pools[name, str(q['qid']), pool] for q in test]))
    multi = {str(q['qid']) for q in test if len(q['gold']) >= 2}
    result = {'review_status': 'pending_expert_review', 'relation_source': args.relations,
              'split': {'dev': [q['qid'] for q in dev], 'test': [q['qid'] for q in test]},
              'limitations': ['Existing benchmark already inspected in earlier experiments; exploratory evaluation',
                              'Predicate name matches are structural candidates, not validated legal dependencies',
                              'All new relations pending expert review; retrieval does not execute rules'],
              'weights_on_dev': chosen, 'mean_candidate_count': candidate_counts,
              'graph_pairs': {n: sum(map(len, g.values())) // 2 for n, g in graphs.items()},
              'test': {n: mean(p) for n, p in per.items()},
              'test_multi': {n: mean({k: v for k, v in p.items() if k in multi}) for n, p in per.items()},
              'sig': {}, 'rankings': {}}
    for pool in ('top20', 'expansion'):
        for baseline in ('Dense', f'old/{pool}'):
            name = f'old+review/{pool}'
            result['sig'][f'{name} vs {baseline}'] = {
                m: randomization(per[baseline], per[name], m) for m in ('R@10', 'NDCG@10', 'Path@10')}
    for q in test:
        k = str(q['qid'])
        result['rankings'][k] = {'gold': q['gold'], 'Dense': sorted(dense[k], key=lambda a: -dense[k][a])[:10]}
        for name in graphs:
            for pool in ('top20', 'expansion'):
                label = f'{name}/{pool}'; s = run(name, pool, chosen[label], k)
                result['rankings'][k][label] = sorted(s, key=lambda a: -s[a])[:10]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('rankings', 'split')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
