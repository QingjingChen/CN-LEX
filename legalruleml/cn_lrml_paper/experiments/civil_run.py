#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B：民法法条检索（LEGO / LexGo 题目 → 《民法典》1260 条）。

方法（同一编码器 BGE-m3，只改变文档表示或图扩展）：
  B1  BM25(text)               原文，字符二元组
  B2  Dense(text)              原文
  B3  Dense(AKN)               + Akoma Ntoso 层级路径（编/分编/章/节）
  B4  Dense(LRML)              + LegalRuleML 语义层（规则层规范、条件、效果、例外；结构层概念）
  B5  Dense(LRML) + 规范关系扩展（override / exception / depends）
  B6  B5 + 结构层同主题关系（cocite）
  消融：Dense(text) + 规范关系扩展；B5 去掉 override+exception（只保留 depends）
  参考：LEGO 专家图谱 GraphRAG 的 top-8（无序，只报 R@8）
图扩展：s'(a) = s(a) + γ · Σ_{b ∈ N(a) ∩ Top10} s(b)，s 为按题 min-max 归一化的余弦。γ 在开发集（30%，seed 0）上选取。
用法：~/.venvs/lcr_jurex/bin/python civil_run.py
"""
import collections, json, os, random
import numpy as np
from retrieval_lib import BM25, embed, minmax, metrics, mean, randomization, HERE

D = json.load(open(os.path.join(HERE, 'data/civil_data.json'), encoding='utf-8'))
ARTS = D['articles']
Q = D['queries']
COVERED = set(D['covered'])
KS = dict(ks_r=(5, 8, 10), ks_n=(10,))
GAMMAS = (0, .05, .1, .2, .3, .5, .75, 1.0)


def dense(view):
    _, A = embed({a: ARTS[a][view] for a in ARTS}, max_len=1024, bs=16)
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    S = X @ A.T
    ids = list(ARTS)
    return {str(q['qid']): {ids[j]: float(S[i, j]) for j in range(len(ids))} for i, q in enumerate(Q)}


def neighbours(types):
    N = collections.defaultdict(dict)
    for t in types:
        for a, b, w in D['edges'].get(t, []):
            a, b = str(a), str(b)
            N[a][b] = N[a].get(b, 0) + 1
            N[b][a] = N[b].get(a, 0) + 1
    return N


def expand(run, N, gamma, top=10):
    if not gamma:
        return run
    out = {}
    for q, s in run.items():
        s = minmax(s)
        topk = sorted(s, key=lambda p: -s[p])[:top]
        add = collections.Counter()
        for b in topk:
            for a in N.get(b, {}):
                add[a] += s[b]
        out[q] = {p: v + gamma * add.get(p, 0) for p, v in s.items()}
    return out


def evaluate(run, qs):
    return {str(q['qid']): metrics(run[str(q['qid'])], {str(a): 1 for a in q['gold']}, **KS) for q in qs}


def main():
    rng = random.Random(0)
    qs = sorted(Q, key=lambda q: q['qid'])
    dev = set(q['qid'] for q in rng.sample(qs, round(.3 * len(qs))))
    DEV = [q for q in qs if q['qid'] in dev]
    TEST = [q for q in qs if q['qid'] not in dev]
    print(f'questions {len(qs)}  dev {len(DEV)}  test {len(TEST)}  test∩rule-covered {sum(q["covered"] for q in TEST)}')

    bm = BM25({a: ARTS[a]['text'] for a in ARTS})
    runs = {'B1 BM25(text)': {str(q['qid']): bm.score(q['text']) for q in Q}}
    for v, name in (('text', 'B2 Dense(text)'), ('akn', 'B3 Dense(AKN)'), ('lrml', 'B4 Dense(LRML)')):
        runs[name] = dense(v)

    NORM = neighbours(['override', 'exception', 'depends'])
    ALL = neighbours(['override', 'exception', 'depends', 'cocite'])
    DEP = neighbours(['depends'])
    tuned = {}

    def tune(base, N, label):
        best = max(GAMMAS, key=lambda g: (mean(evaluate(expand(runs[base], N, g), DEV))['R@10'], -g))
        tuned[label] = best
        runs[label] = expand(runs[base], N, best)

    tune('B4 Dense(LRML)', NORM, 'B5 Dense(LRML)+norm-rel')
    tune('B4 Dense(LRML)', ALL, 'B6 Dense(LRML)+norm+cotopic')
    tune('B2 Dense(text)', NORM, 'A1 Dense(text)+norm-rel')
    tune('B4 Dense(LRML)', DEP, 'A2 Dense(LRML)+depends only')
    print('gamma chosen on dev:', tuned)

    res = {'split': {'dev': len(DEV), 'test': len(TEST)}, 'gamma': tuned, 'test': {}, 'test_covered': {}, 'sig': {}}
    per_all = {}
    for name, run in runs.items():
        per = evaluate(run, TEST)
        per_all[name] = per
        res['test'][name] = mean(per)
        res['test_covered'][name] = mean({q: per[q] for q in per if next(x for x in TEST if str(x['qid']) == q)['covered']})
    # LEGO GraphRAG top-8（无序）
    lego = {}
    for q in TEST:
        g = set(q['gold'])
        lego[str(q['qid'])] = {'R@8': len(g & set(q['lego'])) / len(g)} if q['lego'] else None
    lg = {k: v for k, v in lego.items() if v}
    res['lego_R@8'] = {'n': len(lg), 'all': mean(lg)['R@8'],
                       'covered': mean({k: v for k, v in lg.items() if next(x for x in TEST if str(x['qid']) == k)['covered']})['R@8']}
    base = per_all['B2 Dense(text)']
    for name in runs:
        if name != 'B2 Dense(text)':
            res['sig'][name] = {m: randomization(base, per_all[name], m) for m in ('R@10', 'NDCG@10', 'MRR')}
    # 规则覆盖题上同样做检验
    cov = {str(q['qid']) for q in TEST if q['covered']}
    res['sig_covered'] = {name: {m: randomization({q: base[q] for q in cov}, {q: per_all[name][q] for q in cov}, m)
                                 for m in ('R@10', 'NDCG@10')} for name in runs if name != 'B2 Dense(text)'}
    res['n_test_covered'] = len(cov)
    json.dump(res, open(os.path.join(HERE, 'results/civil_results.json'), 'w'), ensure_ascii=False, indent=1)
    keys = ['R@5', 'R@8', 'R@10', 'NDCG@10', 'MRR']
    print(f"{'method':32s}" + ''.join(f'{k:>9s}' for k in keys) + '   | covered R@10  NDCG@10')
    for name in runs:
        m, c = res['test'][name], res['test_covered'][name]
        print(f'{name:32s}' + ''.join(f'{m[k]:9.4f}' for k in keys) + f"   |  {c['R@10']:.4f}   {c['NDCG@10']:.4f}")
    print(f"LEGO GraphRAG top-8 R@8 (n={res['lego_R@8']['n']}): all {res['lego_R@8']['all']:.4f}  covered {res['lego_R@8']['covered']:.4f}")
    for name, s in res['sig'].items():
        print(f'  vs B2: {name:32s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.4f}' for m, (d, p) in s.items()))
    for name, s in res['sig_covered'].items():
        print(f'  covered vs B2: {name:32s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.4f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    os.makedirs(os.path.join(HERE, 'results'), exist_ok=True)
    main()
