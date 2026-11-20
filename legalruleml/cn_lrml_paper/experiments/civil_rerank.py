#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B（重排序设计）：同一批 Dense Top-20 候选上比较文档层级与规范语义。

  B1  BM25(原文)                    全库排序
  B2  Dense(原文, BGE-m3)            全库排序；其 Top-20 是 B3/B4 的共同候选
  B3  AKN-only                       S = S_dense + w_h·S_hier
  B4a AKN + Element                  S = S_dense + w_h·S_hier + w_e·S_elem
  B4  AKN + Element + Norm           S = S_dense + w_h·S_hier + w_e·S_elem + w_n·S_norm   （= CN-LRML 完整配置）
  B4+ B4 + 图扩展                    候选 = Top-20 ∪ 前 5 名的规范邻居（单独报告，召回范围变大）
各分数先在候选内 min-max 归一化；权重在开发集（30%，seed 0）上按 NDCG@10 网格选取，测试集只报告。

  S_hier(q,a) = Σ_{b∈Top5, b≠a} ŝ(b)·prox(a,b)；prox：同节 1、同章 0.6、同分编 0.3、同编 0.1；显式引用（条文中“第X条”）1
  S_elem(q,a) = cos(q, 要件文本(a))；要件文本 = 人工规则层的 条件 / 效果 / 例外 + support 边指向该条的 card 的 正条件 / 负条件 / 效果，
               card 按 support 权重排序取前 2（只有要件，不含标题和条文原文）
  S_norm(q,a) = Σ_{b∈Top5, b≠a} ŝ(b)·[a, b 有规范关系]；关系 = 人工规则层 override / exception / depends + card 的 exception / priority / related 链接
指标：R@5、R@10、NDCG@10、MRR；Path Recall@10 = 全部金标条文都进入前 10 的题目比例（另报多跳题，金标 ≥ 2 条）。
用法：~/.venvs/lcr_jurex/bin/python civil_rerank.py
"""
import argparse, collections, itertools, json, os, random, re
import numpy as np
from retrieval_lib import BM25, embed, minmax, metrics, mean, randomization, HERE
import civil_run as CR
import civil_full_run as CF

ARTS, Q = CR.ARTS, CR.Q
ids = list(ARTS)
CN = '零一二三四五六七八九十百千'


def levels(a):
    parts = ARTS[a]['akn'].split('\n')[0].split(' / ')
    out = {}
    for p in parts:
        m = re.match(r'第[^编章节]+(分编|编|章|节)', p)
        if m:
            out[m.group(1)] = p
    return out


LV = {a: levels(a) for a in ids}


def prox(a, b):
    la, lb = LV[a], LV[b]
    if la.get('节') and la.get('节') == lb.get('节') and la.get('章') == lb.get('章'):
        return 1.0
    if la.get('章') and la.get('章') == lb.get('章') and la.get('编') == lb.get('编'):
        return 0.6
    if la.get('分编') and la.get('分编') == lb.get('分编'):
        return 0.3
    if la.get('编') and la.get('编') == lb.get('编'):
        return 0.1
    return 0.0


def citations():
    C = collections.defaultdict(set)
    for a in ids:
        for m in re.finditer(r'第([' + CN + r']+)条', ARTS[a]['text'][8:]):     # 跳过条首的“第X条”
            n = str(CR_cn2int(m.group(1)))
            if n in ARTS and n != a:
                C[a].add(n); C[n].add(a)
    return C


def CR_cn2int(s):
    import sys
    sys.path.insert(0, os.path.join(HERE, '../../civil_graph'))
    import civil_code
    return civil_code.cn2int(s)


def element_texts():
    rows = CF.rows
    by_art = collections.defaultdict(list)
    for i, r in enumerate(rows):
        for a, w in CF.W[r['id']].items():
            by_art[a].append((w, i))
    out = {}
    for a in ids:
        parts = []
        lr = ARTS[a]['lrml']
        for line in lr.split('\n'):
            if line.startswith('规范：'):
                parts.append(re.sub(r'^规范：[^。]*。', '', line))
        for w, i in sorted(by_art.get(int(a), []), reverse=True)[:2]:
            c = rows[i]['card']
            parts.append('条件：' + '；'.join(c.get('positive_conditions') or []) + '。例外：' + '；'.join(c.get('negative_conditions') or [])
                         + '。效果：' + '；'.join(c.get('legal_effects') or []) + '。')
        if parts:
            out[a] = '\n'.join(parts)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--review-relations', help='Optional review .lrml (recommended) or legacy relation JSON; all new edges remain pending expert review')
    ap.add_argument('--review-overrides-only', action='store_true', help='Use only explicit override edges from the review export')
    ap.add_argument('--output-prefix', default='civil_rerank', help='Separate results filename prefix; no path components')
    args = ap.parse_args()
    if os.path.basename(args.output_prefix) != args.output_prefix:
        ap.error('--output-prefix must be a filename prefix')
    if args.review_relations and args.output_prefix == 'civil_rerank':
        args.output_prefix = 'civil_rerank_review'
    rng = random.Random(0)
    qs = sorted(Q, key=lambda q: q['qid'])
    dev = set(q['qid'] for q in rng.sample(qs, round(.3 * len(qs))))
    DEV = [q for q in qs if q['qid'] in dev]; TEST = [q for q in qs if q['qid'] not in dev]
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    row = {str(q['qid']): i for i, q in enumerate(Q)}
    _, A = embed({a: ARTS[a]['text'] for a in ARTS}, max_len=1024, bs=16)
    ET = element_texts()
    eids, AE = embed(ET, max_len=1024, bs=16)
    eidx = {a: i for i, a in enumerate(eids)}
    CIT = citations()
    NORM = CF.merge(CR.neighbours(['override', 'exception', 'depends']), CF.card_edges())
    if args.review_relations:
        from civil_review_retrieval import review_neighbours
        new = review_neighbours(args.review_relations, {'override'} if args.review_overrides_only else None)
        NORM = CF.merge(NORM, new)
    print(f'articles with element text: {len(ET)}/{len(ids)}; citation pairs: {sum(map(len, CIT.values())) // 2}; '
          f'norm pairs: {sum(map(len, NORM.values())) // 2}')

    bm = BM25({a: ARTS[a]['text'] for a in ARTS})
    feats = {}
    for q in Q:
        k = str(q['qid']); x = X[row[k]]
        dense = dict(zip(ids, map(float, A @ x)))
        order = sorted(dense, key=lambda p: -dense[p])
        top20, seeds = order[:20], order[:5]
        nb = set(top20) | {n for b in seeds for n in NORM.get(b, {})}
        def build(cands):
            d = minmax({a: dense[a] for a in cands})
            sd = {b: d[b] for b in seeds}
            hier = {a: sum(sd[b] * max(prox(a, b), 1.0 if b in CIT.get(a, ()) else 0) for b in seeds if b != a) for a in cands}
            elem = {a: float(AE[eidx[a]] @ x) if a in eidx else None for a in cands}
            lo = min([v for v in elem.values() if v is not None] or [0])
            elem = {a: (v if v is not None else lo) for a, v in elem.items()}
            norm = {a: sum(sd[b] * (1 if a in NORM.get(b, {}) else 0) for b in seeds if b != a) for a in cands}
            return {'dense': d, 'hier': minmax(hier) if len(set(hier.values())) > 1 else hier,
                    'elem': minmax(elem), 'norm': minmax(norm) if len(set(norm.values())) > 1 else norm}
        feats[k] = {'full_dense': dense, 'top20': build(top20), 'exp': build(sorted(nb)), 'bm25': bm.score(q['text'])}

    def score(k, w, pool):
        f = feats[k][pool]
        return {a: f['dense'][a] + w[0] * f['hier'][a] + w[1] * f['elem'][a] + w[2] * f['norm'][a] for a in f['dense']}

    def ev_run(run, qs):
        out = {}
        for q in qs:
            k = str(q['qid']); rel = {str(g): 1 for g in q['gold']}
            m = metrics(run(k), rel, ks_r=(5, 10, 20), ks_n=(10,))
            s = run(k); top10 = set(sorted(s, key=lambda p: -s[p])[:10])
            m['Path@10'] = float(set(rel) <= top10)
            out[k] = m
        return out

    def full(run_top, k):
        """重排序只改变 Top-20 内部顺序；其余条文保持 Dense 顺序，排在后面。"""
        s = run_top(k); base = feats[k]['full_dense']
        lo = min(s.values()) - 1
        return {a: s.get(a, lo - (1 - base[a])) for a in base}

    grid = [0, .1, .2, .3, .5, .75, 1.0]
    configs = {'B3 AKN-only': (1, 0, 0), 'B4a AKN+Element': (1, 1, 0), 'B4 AKN+Element+Norm': (1, 1, 1)}
    chosen, runs = {}, {}
    runs['B1 BM25'] = lambda k: feats[k]['bm25']
    runs['B2 Dense'] = lambda k: feats[k]['full_dense']
    for name, mask in configs.items():
        cands = [w for w in itertools.product(*[grid if m else [0] for m in mask])]
        best = max(cands, key=lambda w: (mean(ev_run(lambda k: full(lambda kk: score(kk, w, 'top20'), k), DEV))['NDCG@10'], -sum(w)))
        chosen[name] = best
        runs[name] = (lambda w: (lambda k: full(lambda kk: score(kk, w, 'top20'), k)))(best)
    # 消融：只加 Element、只加 Norm（不加层级）
    for name, mask in {'A1 Element-only': (0, 1, 0), 'A2 Norm-only': (0, 0, 1)}.items():
        cands = [w for w in itertools.product(*[grid if m else [0] for m in mask])]
        best = max(cands, key=lambda w: (mean(ev_run(lambda k: full(lambda kk: score(kk, w, 'top20'), k), DEV))['NDCG@10'], -sum(w)))
        chosen[name] = best
        runs[name] = (lambda w: (lambda k: full(lambda kk: score(kk, w, 'top20'), k)))(best)
    wexp = max([w for w in itertools.product(grid, grid, grid)],
               key=lambda w: (mean(ev_run(lambda k: full(lambda kk: score(kk, w, 'exp'), k), DEV))['NDCG@10'], -sum(w)))
    chosen['B4+ expansion'] = wexp
    runs['B4+ expansion'] = lambda k: full(lambda kk: score(kk, wexp, 'exp'), k)

    per = {n: ev_run(r, TEST) for n, r in runs.items()}
    multi = [str(q['qid']) for q in TEST if len(q['gold']) >= 2]
    res = {'weights_on_dev(w_hier,w_elem,w_norm)': chosen, 'n_test': len(TEST), 'n_multi': len(multi),
           'test': {n: mean(p) for n, p in per.items()},
           'test_multi': {n: mean({k: p[k] for k in multi}) for n, p in per.items()}, 'sig': {}}
    if args.review_relations:
        res['review_relations'] = {'path': args.review_relations, 'status': 'pending_expert_review',
                                   'overrides_only': args.review_overrides_only}
    for a, b in [('B2 Dense', 'B3 AKN-only'), ('B2 Dense', 'B4 AKN+Element+Norm'), ('B3 AKN-only', 'B4a AKN+Element'),
                 ('B4a AKN+Element', 'B4 AKN+Element+Norm'), ('B3 AKN-only', 'B4 AKN+Element+Norm'), ('B2 Dense', 'B4+ expansion')]:
        res['sig'][f'{b} vs {a}'] = {m: randomization(per[a], per[b], m) for m in ('R@10', 'NDCG@10', 'Path@10')}
    json.dump(res, open(os.path.join(HERE, f'results/{args.output_prefix}_results.json'), 'w'), ensure_ascii=False, indent=1)
    # 保存每题排序供举例
    dump = {}
    for q in TEST:
        k = str(q['qid'])
        dump[k] = {}
        for n, r in runs.items():
            if n in ('B2 Dense', 'B3 AKN-only', 'B4 AKN+Element+Norm'):
                scores = r(k)
                dump[k][n] = sorted(scores, key=lambda p: -scores[p])[:10]
        dump[k]['gold'] = q['gold']
    json.dump(dump, open(os.path.join(HERE, f'results/{args.output_prefix}_rankings.json'), 'w'), ensure_ascii=False)
    print('weights (w_hier, w_elem, w_norm) chosen on dev:', chosen)
    keys = ['R@5', 'R@10', 'R@20', 'NDCG@10', 'MRR', 'Path@10']
    print(f"{'method':24s}" + ''.join(f'{k:>9s}' for k in keys) + f'  | multi-hop({len(multi)}) R@10 Path@10')
    for n in runs:
        m, mm = res['test'][n], res['test_multi'][n]
        print(f'{n:24s}' + ''.join(f'{m[k]:9.4f}' for k in keys) + f"  |  {mm['R@10']:.4f} {mm['Path@10']:.4f}")
    for n, s in res['sig'].items():
        print(f'  {n:46s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.3f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    main()
