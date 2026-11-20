#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民法法条检索：按关系类型与方向使用规范关系（替代“无向邻接”）。

共同候选：Dense（BGE-m3，条文原文）Top-20；种子 = Top-5。所有变体只重排同一 Top-20（扩展变体单独报告）。
  S(a) = S_dense(a) + w_e·S_elem(a) + Σ_t w_t·N_t(a)
  N_t(a) = min-max( Σ_{b∈种子, b→a ∈ E_t} ŝ_dense(b) )      —— 只沿关系 t 的法律方向传递
关系类型与方向（“b 被检索到 ⇒ 应查阅 a”）：
  override_up     被覆盖的一般规则 → 优先的特别规则      （检索到一般规则时，必须查看覆盖它的规则）
  override_down   优先规则 → 被覆盖规则                  （特别规则的适用语境）
  exception       宿主规则 → 提供其 Naf 例外条件的规则  （检索到原则时查看例外）
  depends         规则 → 提供其前提条件的规则            （检索到规则时查看前提）
  textref         条文 → 其明文引致的条文（仅新图）
  cardlink        LEGO 卡片的主条文 → 卡片写明的例外 / 优先 / 相关条文（旧图，未审核）
图：OLD = civil_graph 人工规则（47 条核对过的 Override、派生 exceptionTo / dependsOn）+ 卡片链接；
    NEW = civil_review.lrml（556 条来源声明的 Override、谓词名称匹配的依赖 / 例外候选、明文引致；全部 pending_expert_review）；
    MERGED = 两者合并。对照：OLD 无向邻接（原 B4 做法）；MERGED 方向反转（检验方向是否有用）。
权重在开发集 76 题上按 NDCG@10 坐标上升选择（每类 {0,.05,.1,.2,.3}），测试集 176 题只报告。
指标：R@5、R@10、P@10、MAP@10、NDCG@10、MRR；路径：PathRecall@10（多跳题中金标条文对同时进入前 10 的比例）、
     CPR@10（Complete Path Rate：全部金标进入前 10 的题目比例）；RelPrec（被关系加分的候选中金标所占比例）。
用法：OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python civil_semantic.py
"""
import collections, itertools, json, math, os, random, re, sys
import numpy as np
from retrieval_lib import embed, minmax, randomization, HERE
import civil_run as CR
import civil_full_run as CF
import civil_rerank as RR
import review_lrml_reader as RV

sys.path.insert(0, os.path.join(HERE, '../../civil_graph'))
import formal_rules as FR  # noqa: E402

ARTS, Q = CR.ARTS, CR.Q
IDS = list(ARTS)
GRID = (0, .05, .1, .2, .3)
TYPES = ('override_up', 'override_down', 'exception', 'depends', 'textref', 'cardlink')


# ---------------------------------------------------------------- 有向、分类型的条文图
def add(E, t, A, B):
    for a in A:
        for b in B:
            a, b = str(a), str(b)
            if a != b and a in ARTS and b in ARTS:
                E[t][a].add(b)


def preds(lits):
    for l in lits:
        for x in (l[1] if isinstance(l, tuple) else [l]):
            for y in x.split(' '):
                m = re.match(r'([-~]?)(\w+)\(', y)
                if m:
                    yield m.group(1), m.group(2)


def old_graph():
    E = collections.defaultdict(lambda: collections.defaultdict(set))
    rules = [r for _, rs in FR.MODULES.values() for r in rs]
    RA = {r['key']: {int(re.match(r'art(\d+)', s).group(1)) for s in r['srcs']} for r in rules}
    prod = collections.defaultdict(set)
    for r in rules:
        for h in (r['heads'] if isinstance(r['heads'], list) else [r['heads']]):
            h = h if isinstance(h, str) else h[-1]
            prod[re.match(r'-?(\w+)', h).group(1)].add(r['key'])
    for over, under, _ in FR.OVERRIDES:
        add(E, 'override_up', RA[under], RA[over]); add(E, 'override_down', RA[over], RA[under])
    for r in rules:
        for sign, p in preds(r['body']):
            for k in prod.get(p, ()):
                if k != r['key']:
                    add(E, 'exception' if sign == '~' else 'depends', RA[r['key']], RA[k])
    for r in CF.G['relations']:
        if r['type'] == 'distinguish':
            continue
        tgt = [r['to']] if r['to_type'] == 'article' else CF.home.get(r['to'], [])
        add(E, 'cardlink', CF.home.get(r['from'], []), tgt)
    return E


def new_graph():
    E = collections.defaultdict(lambda: collections.defaultdict(set))
    d = RV.ReviewLRML(os.path.join(HERE, '../lrml/civil_review.lrml'))
    for r in d.iter_relations():
        t, A, B = r['type'], r.get('from_articles', []), r.get('to_articles', [])
        if t == 'override':
            add(E, 'override_up', B, A); add(E, 'override_down', A, B)
        elif t == 'depends_candidate':
            add(E, 'depends', A, B)
        elif t in ('exception_candidate', 'negative_condition_candidate'):
            add(E, 'exception', A, B)
        elif t == 'explicit_text_reference':
            add(E, 'textref', A, B)
    return E


def merge(*Gs):
    E = collections.defaultdict(lambda: collections.defaultdict(set))
    for G in Gs:
        for t, adj in G.items():
            for a, bs in adj.items():
                E[t][a] |= bs
    return E


def reverse(G):
    E = collections.defaultdict(lambda: collections.defaultdict(set))
    for t, adj in G.items():
        for a, bs in adj.items():
            for b in bs:
                E[t][b].add(a)
    return E


def undirected(G):
    """原做法：所有类型合成一类、无向。"""
    E = collections.defaultdict(lambda: collections.defaultdict(set))
    for t, adj in G.items():
        for a, bs in adj.items():
            for b in bs:
                E['any'][a].add(b); E['any'][b].add(a)
    return E


def stats(G):
    return {t: sum(map(len, adj.values())) for t, adj in G.items()}


# ---------------------------------------------------------------- 特征
def features():
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    _, A = embed({a: ARTS[a]['text'] for a in ARTS}, max_len=1024, bs=16)
    ET = RR.element_texts()
    eids, AE = embed(ET, max_len=1024, bs=16)
    eix = {a: i for i, a in enumerate(eids)}
    F = {}
    for i, q in enumerate(Q):
        x = X[i]
        dense = dict(zip(IDS, map(float, A @ x)))
        order = sorted(dense, key=lambda p: -dense[p])
        elem = {a: (float(AE[eix[a]] @ x) if a in eix else None) for a in IDS}
        F[str(q['qid'])] = {'dense': dense, 'order': order, 'elem': elem}
    return F


def norm_evidence(G, cands, seeds, sd):
    out = {}
    for t, adj in G.items():
        v = {a: sum(sd[b] for b in seeds if b != a and a in adj.get(b, ())) for a in cands}
        out[t] = minmax(v) if len(set(v.values())) > 1 else {a: 0.0 for a in cands}
    return out


def build(F, G, k, expand=False):
    f = F[k]; seeds = f['order'][:5]
    cands = list(f['order'][:20])
    if expand:
        extra = {b for t, adj in G.items() for s in seeds for b in adj.get(s, ())}
        cands = list(dict.fromkeys(cands + sorted(extra)))
    d = minmax({a: f['dense'][a] for a in cands})
    sd = {b: d[b] for b in seeds}
    el = {a: f['elem'][a] for a in cands}
    lo = min([v for v in el.values() if v is not None] or [0])
    el = minmax({a: (v if v is not None else lo) for a, v in el.items()})
    return {'cands': cands, 'dense': d, 'elem': el, 'norm': norm_evidence(G, cands, seeds, sd)}


def rank(P, F, k, w):
    p = P[k]; types = list(p['norm'])
    s = {a: p['dense'][a] + w.get('elem', 0) * p['elem'][a] + sum(w.get(t, 0) * p['norm'][t][a] for t in types) for a in p['cands']}
    base = F[k]['dense']; lo = min(s.values()) - 1
    full = {a: s.get(a, lo - (1 - base[a])) for a in base}
    return full, {a for a in p['cands'] if any(w.get(t, 0) > 0 and p['norm'][t][a] > 0 for t in types)}


# ---------------------------------------------------------------- 指标
def metrics(scores, gold, boosted):
    ranked = sorted(scores, key=lambda a: -scores[a]); top = ranked[:10]; g = set(gold)
    dcg = sum(1 / math.log2(i + 2) for i, a in enumerate(top) if a in g)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(g), 10)))
    hits, ap = 0, 0.0
    for i, a in enumerate(top):
        if a in g:
            hits += 1; ap += hits / (i + 1)
    pairs = list(itertools.combinations(sorted(g), 2))
    return {'R@5': len(g & set(ranked[:5])) / len(g), 'R@10': len(g & set(top)) / len(g), 'P@10': len(g & set(top)) / 10,
            'MAP@10': ap / min(len(g), 10), 'NDCG@10': dcg / idcg, 'MRR': next((1 / (i + 1) for i, a in enumerate(ranked) if a in g), 0),
            'CPR@10': float(g <= set(top)),
            'PathRecall@10': (sum(a in top and b in top for a, b in pairs) / len(pairs)) if pairs else None,
            'boost_n': len(boosted), 'boost_gold': len(boosted & g)}


def evaluate(P, F, qs, w):
    per = {}
    for q in qs:
        k = str(q['qid']); s, b = rank(P, F, k, w)
        per[k] = metrics(s, {str(a) for a in q['gold']}, b)
    return per


def mean(per, key):
    v = [m[key] for m in per.values() if m[key] is not None]
    return float(np.mean(v)) if v else None


def tune(P, F, DEV, types, with_elem=True):
    w = {t: 0 for t in types}
    if with_elem:
        w['elem'] = max(GRID, key=lambda x: (mean(evaluate(P, F, DEV, {'elem': x}), 'NDCG@10'), -x))
    for _ in range(2):
        for t in types:
            w[t] = max(GRID, key=lambda x: (mean(evaluate(P, F, DEV, dict(w, **{t: x})), 'NDCG@10'), -x))
    return w


def main():
    rng = random.Random(0)
    qs = sorted(Q, key=lambda q: q['qid'])
    dev = set(q['qid'] for q in rng.sample(qs, round(.3 * len(qs))))
    DEV = [q for q in qs if q['qid'] in dev]; TEST = [q for q in qs if q['qid'] not in dev]
    F = features()
    OLD, NEW = old_graph(), new_graph()
    MER = merge(OLD, NEW)
    graphs = {'OLD undirected (previous B4)': undirected(OLD), 'OLD typed+directed': OLD, 'NEW typed+directed': NEW,
              'MERGED typed+directed': MER, 'MERGED reversed (control)': reverse(MER)}
    res = {'graph_edges': {n: stats(g) for n, g in graphs.items()}, 'weights': {}, 'test': {}, 'multi': {}, 'relprec': {}, 'sig': {}}
    per_all = {}
    P0 = {str(q['qid']): build(F, {}, str(q['qid'])) for q in Q}
    per_all['Dense'] = evaluate(P0, F, TEST, {})
    w_e = tune(P0, F, DEV, [], True); res['weights']['Dense + elements'] = w_e
    per_all['Dense + elements'] = evaluate(P0, F, TEST, w_e)
    for name, G in graphs.items():
        P = {str(q['qid']): build(F, G, str(q['qid'])) for q in Q}
        types = list(G)
        w = tune(P, F, DEV, types, True); res['weights'][name] = w
        per_all[name] = evaluate(P, F, TEST, w)
    # 扩展（候选池变大，单独报告）
    PX = {str(q['qid']): build(F, MER, str(q['qid']), expand=True) for q in Q}
    wx = tune(PX, F, DEV, list(MER), True); res['weights']['MERGED typed+directed, expansion'] = wx
    per_all['MERGED typed+directed, expansion'] = evaluate(PX, F, TEST, wx)
    # 消融：MERGED 中只保留一类关系
    for t in TYPES:
        if t not in MER:
            continue
        Gt = {t: MER[t]}
        P = {str(q['qid']): build(F, Gt, str(q['qid'])) for q in Q}
        w = tune(P, F, DEV, [t], True); res['weights'][f'only {t}'] = w
        per_all[f'only {t}'] = evaluate(P, F, TEST, w)
    multi = {str(q['qid']) for q in TEST if len(q['gold']) >= 2}
    keys = ['R@5', 'R@10', 'P@10', 'MAP@10', 'NDCG@10', 'MRR', 'CPR@10', 'PathRecall@10']
    for n, per in per_all.items():
        res['test'][n] = {k: mean(per, k) for k in keys}
        res['multi'][n] = {k: mean({q: per[q] for q in multi}, k) for k in ('R@10', 'NDCG@10', 'CPR@10', 'PathRecall@10')}
        bn = sum(m['boost_n'] for m in per.values()); bg = sum(m['boost_gold'] for m in per.values())
        res['relprec'][n] = {'boosted': bn, 'gold': bg, 'precision': (bg / bn) if bn else None}
    def rnd(a, b, m, ids=None):
        A = {q: {m: v[m]} for q, v in per_all[a].items() if ids is None or q in ids}
        B = {q: {m: v[m]} for q, v in per_all[b].items() if ids is None or q in ids}
        return randomization(A, B, m)
    for a, b in [('Dense', 'Dense + elements'), ('Dense + elements', 'OLD undirected (previous B4)'),
                 ('Dense + elements', 'OLD typed+directed'), ('Dense + elements', 'NEW typed+directed'),
                 ('Dense + elements', 'MERGED typed+directed'), ('OLD undirected (previous B4)', 'OLD typed+directed'),
                 ('OLD typed+directed', 'NEW typed+directed'), ('OLD typed+directed', 'MERGED typed+directed'),
                 ('MERGED reversed (control)', 'MERGED typed+directed'), ('Dense', 'MERGED typed+directed'),
                 ('Dense', 'MERGED typed+directed, expansion')]:
        res['sig'][f'{b} vs {a}'] = {m: rnd(a, b, m) for m in ('R@10', 'NDCG@10', 'MAP@10', 'CPR@10')}
        res['sig'][f'{b} vs {a}']['multi CPR@10'] = rnd(a, b, 'CPR@10', multi)
    res['n_test'], res['n_multi'] = len(TEST), len(multi)
    json.dump(res, open(os.path.join(HERE, 'results/civil_semantic_results.json'), 'w'), ensure_ascii=False, indent=1)
    print('edges:', json.dumps(res['graph_edges'], ensure_ascii=False))
    print(f"{'variant':36s}" + ''.join(f'{k:>11s}' for k in keys) + '  | multi CPR  PathR | RelPrec')
    for n in per_all:
        m, mm, rp = res['test'][n], res['multi'][n], res['relprec'][n]
        print(f'{n:36s}' + ''.join(f'{m[k]:11.4f}' for k in keys) + f"  | {mm['CPR@10']:.4f} {mm['PathRecall@10']:.4f} | "
              + (f"{rp['precision']:.3f} ({rp['gold']}/{rp['boosted']})" if rp['precision'] is not None else '-'))
    print('weights:', json.dumps(res['weights']))
    for n, s in res['sig'].items():
        print(f'  {n:62s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.3f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    main()
