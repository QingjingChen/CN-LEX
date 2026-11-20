#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B2：法条补全（不调参）。给定第一跳检索结果（LEGO top-8 或 Dense top-8），按三种方式各补入同样数量的条文：
  LRML   规范关系邻居（override / exception / depends）
  AKN    同一章内条号最近的条文（文档层级邻近）
  DENSE  Dense 排名中接下来的条文（检索预算对照）
对每题，AKN 与 DENSE 补入的数量 = LRML 补入的数量，因此三者预算相同。
用法：~/.venvs/lcr_jurex/bin/python civil_completion.py
"""
import collections, json, os, re
from retrieval_lib import embed, randomization, HERE

D = json.load(open(os.path.join(HERE, 'data/civil_data.json'), encoding='utf-8'))
ARTS, Q = D['articles'], D['queries']
N = collections.defaultdict(set)
for t in ('override', 'exception', 'depends'):
    for a, b, _ in D['edges'][t]:
        N[a].add(b); N[b].add(a)
chap = {int(a): re.sub(r' / 第[一二三四五六七八九十]+节.*', '', v['akn'].split('\n')[0]) for a, v in ARTS.items()}


def dense_rank():
    ids, A = embed({a: ARTS[a]['text'] for a in ARTS}, max_len=1024, bs=16)
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    S = X @ A.T
    return {q['qid']: [int(ids[j]) for j in (-S[i]).argsort()] for i, q in enumerate(Q)}


def akn_neighbours(base, k):
    cand = set()
    for b in base:
        for d in range(1, 40):
            for a in (b - d, b + d):
                if 1 <= a <= 1260 and a not in base and chap.get(a) == chap.get(b):
                    cand.add((d, a))
    return [a for _, a in sorted(cand)][:k]


def main():
    rank = dense_rank()
    out = {}
    for src in ('LEGO top-8', 'Dense top-8'):
        rows = []
        for q in Q:
            base = q['lego'] if src == 'LEGO top-8' else rank[q['qid']][:8]
            if not base:
                continue
            base, gold = set(base), set(q['gold'])
            lr = sorted(set().union(*(N.get(b, set()) for b in base)) - base)
            k = len(lr)
            ak = akn_neighbours(base, k)
            dn = [a for a in rank[q['qid']] if a not in base][:k]
            r = lambda s: len(gold & s) / len(gold)
            rows.append(dict(qid=q['qid'], k=k, covered=q['covered'], base=r(base), LRML=r(base | set(lr)),
                             AKN=r(base | set(ak)), DENSE=r(base | set(dn)),
                             hitL=len((gold - base) & set(lr)), hitA=len((gold - base) & set(ak)), hitD=len((gold - base) & set(dn)),
                             nA=len(ak)))
        fired = [x for x in rows if x['k']]
        def avg(xs, key): return sum(x[key] for x in xs) / len(xs) if xs else 0
        res = {'n': len(rows), 'n_fired': len(fired), 'mean_added_when_fired': avg(fired, 'k'),
               'missing_gold': sum(len(set(q['gold'])) for q in Q) and None}
        for subset, xs in (('all', rows), ('fired', fired)):
            res[subset] = {m: avg(xs, m) for m in ('base', 'LRML', 'AKN', 'DENSE')}
            res[subset].update({f'recovered_{m}': sum(x['hit' + m[0]] for x in xs) for m in ('LRML', 'AKN', 'DENSE')})
            res[subset]['added'] = sum(x['k'] for x in xs)
            res[subset]['added_AKN'] = sum(x['nA'] for x in xs)
        per = lambda key: {x['qid']: {'R': x[key]} for x in rows}
        res['sig'] = {'LRML vs AKN': randomization(per('AKN'), per('LRML'), 'R'),
                      'LRML vs DENSE': randomization(per('DENSE'), per('LRML'), 'R'),
                      'LRML vs base': randomization(per('base'), per('LRML'), 'R')}
        out[src] = res
        print(f"== {src}: n={res['n']}  expansion fired on {res['n_fired']} questions, mean +{res['mean_added_when_fired']:.2f} articles")
        for s in ('all', 'fired'):
            m = res[s]
            print(f"  [{s:5s}] recall base {m['base']:.4f} | +LRML {m['LRML']:.4f} (+{m['recovered_LRML']} gold / {m['added']} added)"
                  f" | +AKN {m['AKN']:.4f} (+{m['recovered_AKN']} / {m['added_AKN']}) | +DENSE {m['DENSE']:.4f} (+{m['recovered_DENSE']})")
        print('  ', {k: (round(d, 4), round(p, 4)) for k, (d, p) in res['sig'].items()})
    json.dump(out, open(os.path.join(HERE, 'results/civil_completion.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
