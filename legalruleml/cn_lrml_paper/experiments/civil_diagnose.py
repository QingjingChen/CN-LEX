#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B 的诊断分析（只读已缓存的嵌入，不调参）：
  1. AKN 层级为什么变差：逐题胜负、金标排名变化、超过金标的条文是否与金标同章、同章文档是否被“拉近”。
     另试两种用法：层级与原文分开编码后加权融合（late fusion），以及只加最低一级标题。
  2. LRML 语义层的覆盖与质量：金标条文有多少带语义层文本；带 / 不带语义层的金标排名变化。
  3. 规范关系扩展（NDCG@10 +1.3）的来源：按边类型拆分；被提升的金标与触发它的 top-10 条文是什么关系。
  4. 统计功效：176 题上 R@10 差值的 bootstrap 置信区间，以及达到显著所需的大致题量。
用法：~/.venvs/lcr_jurex/bin/python civil_diagnose.py
"""
import collections, json, os, random, re
import numpy as np
from retrieval_lib import embed, metrics, minmax, HERE
import civil_run as CR

D, ARTS, Q = CR.D, CR.ARTS, CR.Q
ids = list(ARTS)


def matrix(view_texts):
    _, A = embed(view_texts, max_len=1024, bs=16)
    return A


_, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
A_text = matrix({a: ARTS[a]['text'] for a in ARTS})
A_akn = matrix({a: ARTS[a]['akn'] for a in ARTS})
A_lrml = matrix({a: ARTS[a]['lrml'] for a in ARTS})
path = {a: ARTS[a]['akn'].split('\n')[0] for a in ARTS}
chap = {a: re.sub(r' / 第[一二三四五六七八九十]+节.*', '', p) for a, p in path.items()}
leaf = {a: p.split(' / ')[-1] for a, p in path.items()}
A_leaf = matrix({a: leaf[a] + '\n' + ARTS[a]['text'] for a in ARTS})
A_path = matrix({a: path[a] or '（无）' for a in ARTS})

rng = random.Random(0)
qs = sorted(Q, key=lambda q: q['qid'])
dev = set(q['qid'] for q in rng.sample(qs, round(.3 * len(qs))))
TEST = [q for q in qs if q['qid'] not in dev]
row = {str(q['qid']): i for i, q in enumerate(Q)}


def run_of(A, extra=None, w=0.0):
    out = {}
    for q in TEST:
        s = X[row[str(q['qid'])]] @ A.T
        if extra is not None:
            s = s + w * (X[row[str(q['qid'])]] @ extra.T)
        out[str(q['qid'])] = dict(zip(ids, map(float, s)))
    return out


def ranks(run, q):
    s = run[str(q['qid'])]
    order = sorted(s, key=lambda p: -s[p])
    pos = {p: i + 1 for i, p in enumerate(order)}
    return order, {str(g): pos[str(g)] for g in q['gold']}


def ev(run):
    per = {str(q['qid']): metrics(run[str(q['qid'])], {str(g): 1 for g in q['gold']}, ks_r=(5, 10), ks_n=(10,)) for q in TEST}
    return per, {k: float(np.mean([v[k] for v in per.values()])) for k in ('R@5', 'R@10', 'NDCG@10')}


out = {}
# ------------------------------------------------------------------ 1. AKN
r_text, r_akn = run_of(A_text), run_of(A_akn)
p_text, m_text = ev(r_text)
p_akn, m_akn = ev(r_akn)
win = sum(p_akn[q]['R@10'] > p_text[q]['R@10'] for q in p_text)
loss = sum(p_akn[q]['R@10'] < p_text[q]['R@10'] for q in p_text)
delta, overtakers_same, overtakers_total, chap_size = [], 0, 0, collections.Counter(chap.values())
for q in TEST:
    o_t, rk_t = ranks(r_text, q)
    o_a, rk_a = ranks(r_akn, q)
    for g in rk_t:
        delta.append(rk_a[g] - rk_t[g])
        if rk_a[g] > rk_t[g]:   # 金标在 AKN 下掉名次：看是谁超过了它
            before = set(o_t[:rk_t[g]])
            for p in o_a[:rk_a[g] - 1]:
                if p not in before:
                    overtakers_total += 1
                    overtakers_same += chap[p] == chap[g]
# 同章文档在两种视图下的平均两两相似度（“拉近”效应）
def intra(A):
    by = collections.defaultdict(list)
    for i, a in enumerate(ids):
        by[chap[a]].append(i)
    sims = []
    for c, ix in by.items():
        if len(ix) > 1:
            M = A[ix] @ A[ix].T
            sims.append((M.sum() - len(ix)) / (len(ix) * (len(ix) - 1)))
    return float(np.mean(sims))
def inter(A, n=4000, seed=1):
    r = random.Random(seed); s = []
    while len(s) < n:
        i, j = r.randrange(len(ids)), r.randrange(len(ids))
        if chap[ids[i]] != chap[ids[j]]:
            s.append(float(A[i] @ A[j]))
    return float(np.mean(s))
# 查询与“金标所在章标题”的相似度 vs 与“排名第一的错误条文所在章标题”的相似度
qpath_gold, qpath_top = [], []
for q in TEST:
    x = X[row[str(q['qid'])]]
    g = str(q['gold'][0])
    qpath_gold.append(float(x @ A_path[ids.index(g)]))
    o, _ = ranks(r_text, q)
    wrong = next(p for p in o if int(p) not in q['gold'])
    qpath_top.append(float(x @ A_path[ids.index(wrong)]))
gold_path_len = np.mean([len(path[str(g)]) for q in TEST for g in q['gold']])
gold_text_len = np.mean([len(ARTS[str(g)]['text']) for q in TEST for g in q['gold']])
fus = {}
for w in (0.1, 0.2, 0.3):
    fus[w] = ev(run_of(A_text, A_path, w))[1]
out['akn'] = {'text': m_text, 'akn': m_akn, 'leaf_only': ev(run_of(A_leaf))[1], 'late_fusion': fus,
              'R@10_win_loss': [win, loss], 'gold_rank_change_median': float(np.median(delta)),
              'gold_rank_up_down_same': [sum(d < 0 for d in delta), sum(d > 0 for d in delta), sum(d == 0 for d in delta)],
              'overtakers_same_chapter': [overtakers_same, overtakers_total],
              'intra_chapter_cos': {'text': intra(A_text), 'akn': intra(A_akn)},
              'inter_chapter_cos': {'text': inter(A_text), 'akn': inter(A_akn)},
              'mean_gold_path_len': float(gold_path_len), 'mean_gold_text_len': float(gold_text_len),
              'query_vs_chapter_title_cos': {'gold_chapter': float(np.mean(qpath_gold)), 'top_wrong_chapter': float(np.mean(qpath_top)),
                                             'gold_chapter_higher_share': float(np.mean([a > b for a, b in zip(qpath_gold, qpath_top)]))},
              'gold_same_chapter_as_top_wrong': float(np.mean([chap[str(q['gold'][0])] == chap[next(p for p in ranks(r_text, q)[0] if int(p) not in q['gold'])] for q in TEST]))}

# ------------------------------------------------------------------ 2. LRML 覆盖与质量
r_lrml = run_of(A_lrml)
p_lrml, m_lrml = ev(r_lrml)
rule_arts = {a for a in ARTS if '规范：' in ARTS[a]['lrml']}
concept_arts = {a for a in ARTS if '概念：' in ARTS[a]['lrml']}
golds = [str(g) for q in TEST for g in q['gold']]
dl = {'rule': [], 'concept_only': [], 'none': []}
for q in TEST:
    _, rt = ranks(r_text, q); _, rl = ranks(r_lrml, q)
    for g in rt:
        k = 'rule' if g in rule_arts else 'concept_only' if g in concept_arts else 'none'
        dl[k].append(rl[g] - rt[g])
added = [len(ARTS[a]['lrml']) - len(ARTS[a]['akn']) for a in rule_arts]
# 语义层文本里“通用效果词”的比例（区分度低）
eff = collections.Counter()
for a in rule_arts:
    for m in re.finditer(r'效果：([^。]*)。', ARTS[a]['lrml']):
        for e in m.group(1).split('、'):
            eff[e] += 1
out['lrml'] = {'text': m_text, 'lrml': m_lrml,
               'gold_with_rule_text': [sum(g in rule_arts for g in golds), len(golds)],
               'gold_with_concepts_only': sum(g in concept_arts and g not in rule_arts for g in golds),
               'rank_change_by_group': {k: {'n': len(v), 'median': float(np.median(v)) if v else None,
                                            'up': sum(d < 0 for d in v), 'down': sum(d > 0 for d in v)} for k, v in dl.items()},
               'mean_added_chars_rule_articles': float(np.mean(added)),
               'top_effect_glosses': eff.most_common(8)}

# ------------------------------------------------------------------ 3. 规范关系扩展
typed = {t: CR.neighbours([t]) for t in ('override', 'exception', 'depends', 'cocite')}
allnorm = CR.neighbours(['override', 'exception', 'depends'])
base_run = {str(q['qid']): CR.dense('text')[str(q['qid'])] for q in TEST}
_, m_base = ev(base_run)
res3 = {'base': m_base}
for name, N in list(typed.items()) + [('all_normative', allnorm)]:
    res3[name] = ev(CR.expand(base_run, N, 0.05))[1]
exp_run = CR.expand(base_run, allnorm, 0.05)
p_b, _ = ev(base_run); p_e, _ = ev(exp_run)
improved, hurt, cases = [], [], []
for q in TEST:
    k = str(q['qid'])
    d = p_e[k]['NDCG@10'] - p_b[k]['NDCG@10']
    if abs(d) < 1e-9:
        continue
    (improved if d > 0 else hurt).append(k)
    o_b, rb = ranks(base_run, q); o_e, re_ = ranks(exp_run, q)
    top = o_b[:10]
    for g in rb:
        if re_[g] != rb[g]:
            via = [(t, b) for t, N in typed.items() for b in top if g in N.get(b, {})]
            cases.append({'qid': q['qid'], 'gold': int(g), 'rank': [rb[g], re_[g]], 'via': [(t, int(b)) for t, b in via][:4],
                          'gold_in_top10_before': rb[g] <= 10})
moved_up = [c for c in cases if c['rank'][1] < c['rank'][0]]
out['relations'] = {'by_edge_type': res3, 'questions_improved': len(improved), 'questions_hurt': len(hurt),
                    'gold_moves_up': len(moved_up), 'gold_moves_down': len(cases) - len(moved_up),
                    'up_already_in_top10': sum(c['gold_in_top10_before'] for c in moved_up),
                    'up_edge_types': collections.Counter(t for c in moved_up for t, _ in c['via']).most_common(),
                    'examples_up': sorted(moved_up, key=lambda c: c['rank'][1] - c['rank'][0])[:8]}

# ------------------------------------------------------------------ 4. 统计功效
def boot(pa, pb, metric, n=5000, seed=0):
    ks = list(pa); r = random.Random(seed); d = np.array([pb[k][metric] - pa[k][metric] for k in ks])
    bs = [d[[r.randrange(len(d)) for _ in d]].mean() for _ in range(n)]
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), float(d.std(ddof=1))
power = {}
for name, pb in (('akn', p_akn), ('lrml', p_lrml)):
    m, lo, hi, sd = boot(p_text, pb, 'R@10')
    need = (2.8 * sd / m) ** 2 if m else None      # 双侧 α=.05、功效 80% 时检出当前效应所需题数（配对 z 近似）
    power[name] = {'dR@10': m, 'CI95': [lo, hi], 'sd_per_q': sd, 'n_needed_for_80pct_power': need}
cov = [k for k in p_text if next(q for q in TEST if str(q['qid']) == k)['covered']]
m, lo, hi, sd = boot({k: p_text[k] for k in cov}, {k: p_lrml[k] for k in cov}, 'R@10')
power['lrml_covered'] = {'dR@10': m, 'CI95': [lo, hi], 'sd_per_q': sd, 'n_needed_for_80pct_power': (2.8 * sd / m) ** 2}
out['power'] = power
json.dump(out, open(os.path.join(HERE, 'results/civil_diagnose.json'), 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
