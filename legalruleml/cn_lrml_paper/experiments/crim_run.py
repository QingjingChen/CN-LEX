#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 A：刑事类案检索（JUREX-4E 第 8 节设定：LeCaRDv2 / GEAR 1390 候选子集，54 个测试查询）。

查询只有案情事实；候选是已决案件，其罪名已知（pid_charges）。我们用罪名知识把查询“投影”到罪名空间：
  p(c|q) = softmax_c( cos(E_q, E_c) / τ )，E_c 为罪名表示的嵌入；
  sig(q,d) = min(1, Σ_{c ∈ C_d} p(c|q))；  score = minmax(cos(q,d)) + λ · sig(q,d)
罪名表示（只改变这一项）：
  STAT   罪名 + 《刑法》对应条文原文（crime2article）            —— 文档层（AKN 条文）
  JUREX  罪名 + JUREX-4E 专家四要件（Expert-FET）                —— 专家知识（对照）
  LRML   罪名 + 刑法 LegalRuleML 图谱的概念与四要件（结构层）     —— 本文
  LRML+R LRML + 罪名间关系（转化 / 此罪与彼罪，结构层 conv 节点）：p'(c) = p(c) + β Σ_{c'~c} p(c')
没有图谱 / JUREX 条目的罪名回退到 STAT。λ、τ、β 只在 599 个非测试查询上选。
另报：罪名预测（Hit@1 / R@3，测试查询的金标罪名）与“金标罪名”上界（ORACLE：sig = |C_d ∩ C_q| / |C_q|）。
用法：~/.venvs/lcr_jurex/bin/python crim_run.py
"""
import itertools, json, os, sys
import numpy as np
from retrieval_lib import BM25, embed, minmax, metrics, mean, randomization, HERE

LCR = os.path.join(HERE, '../../lcr_jurex')
G = os.path.join(LCR, 'data/gear')
J = lambda p: json.load(open(p, encoding='utf-8'))
labels = J(f'{G}/labels.json')
qsent = J(f'{G}/qid_sentences.json')
psent = J(f'{G}/pid_sentences.json')
pchg = J(f'{G}/pid_charges.json')
test_list = J(f'{G}/test_qids.json')
TEST = list(dict.fromkeys(test_list))
qchg = {}
for q, cs in zip(test_list, J(f'{G}/test_q_charges.json')):
    qchg[q] = cs
TRAIN = [q for q in labels if q not in set(TEST) and q in qsent]
REL = {q: {p: l for p, l in labels[q]} for q in labels}
KS = dict(ks_r=(1, 5, 10, 30), ks_n=(10, 30))

CHARGES = sorted({c for v in pchg.values() for c in v})
c2a = J(os.path.join(LCR, 'data/jurex/crime2article.json'))
c2a['非法采伐、毁坏国家重点保护植物'] = [344]
law = J(os.path.join(HERE, '../../crim_graph/law/criminal_law_2023.json'))
jurex = {list(x)[0]: list(x.values())[0] for x in J(os.path.join(LCR, 'data/jurex/jurex4e.json'))}
kb = J(os.path.join(LCR, 'data/lrml_kb.json'))
FET = ('犯罪客体', '客观方面', '犯罪主体', '主观方面')


def stat_text(c):
    arts = c2a.get(c.rstrip('罪'), c2a.get(c, []))
    return c + '。' + ''.join(''.join(law[str(a)]['paras']) for a in arts if str(a) in law)


def jurex_text(c):
    f = jurex.get(c)
    if not f:
        return stat_text(c)
    return c + '。' + ''.join(f'{k}：' + '；'.join(x['title'] for x in f.get(k, [])) + '。' for k in FET)


def lrml_text(c):
    k = kb.get(c)
    if not k:
        return stat_text(c)
    return c + '。' + k.get('concept', '') + '。' + ''.join(f'{x}：{k["fet"].get(x, "")}。' for x in FET)


def relations():
    """罪名关系：图谱中某罪名“此罪与彼罪 / 转化”条件节点里提到的另一罪名。"""
    R = {c: set() for c in CHARGES}
    for c, k in kb.items():
        if c not in R:
            continue
        for x in k['conditions']:
            if x['type'] != 'conv':
                continue
            for d in CHARGES:
                if d != c and d.rstrip('罪') in x['text']:
                    R[c].add(d); R[d].add(c)
    return R


def charge_probs(Xq, qids, rep, tau):
    _, C = embed({c: rep(c) for c in CHARGES}, max_len=2048, bs=8)
    S = Xq @ C.T / tau
    S = np.exp(S - S.max(1, keepdims=True))
    P = S / S.sum(1, keepdims=True)
    return {q: dict(zip(CHARGES, P[i])) for i, q in enumerate(qids)}


def propagate(P, R, beta):
    if not beta:
        return P
    out = {}
    for q, p in P.items():
        o = {c: v + beta * sum(p[d] for d in R[c]) for c, v in p.items()}
        z = sum(o.values())
        out[q] = {c: v / z for c, v in o.items()}
    return out


def fuse(base, P, lam):
    out = {}
    for q, s in base.items():
        s = minmax(s)
        p = P[q]
        out[q] = {d: v + lam * min(1.0, sum(p.get(c, 0) for c in pchg.get(d, []))) for d, v in s.items()}
    return out


def ev(run, qs):
    return {q: metrics(run[q], REL[q], **KS) for q in qs}


def main():
    qids = TEST + TRAIN
    _, Xq = embed({q: ''.join(qsent[q]) for q in qids}, max_len=8192, bs=4)
    pids, Xc = embed({p: ''.join(psent[p]) for p in psent}, max_len=8192, bs=4)
    S = Xq @ Xc.T
    dense = {q: {p: float(S[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(qids)}
    bm = BM25({p: ''.join(psent[p]) for p in psent})
    bm25 = {q: bm.score(''.join(qsent[q])) for q in TEST}
    R = relations()
    print(f'test {len(TEST)}  train {len(TRAIN)}  charges {len(CHARGES)}  with LRML {sum(c in kb for c in CHARGES)}'
          f'  with JUREX {sum(c in jurex for c in CHARGES)}  relation pairs {sum(map(len, R.values())) // 2}')

    reps = {'STAT': stat_text, 'JUREX': jurex_text, 'LRML': lrml_text}
    runs = {'BM25(fact)': bm25, 'Dense(fact)': dense}
    chosen, cpred = {}, {}
    for name, rep in list(reps.items()) + [('LRML+R', lrml_text)]:
        betas = (0, .25, .5, 1.0) if name == 'LRML+R' else (0,)
        best = None
        for tau, beta in itertools.product((.02, .05, .1), betas):
            P = propagate(charge_probs(Xq, qids, rep, tau), R, beta)
            for lam in (0, .05, .1, .2, .3, .5, .75, 1.0):
                f = fuse({q: dense[q] for q in TRAIN}, P, lam)
                m = mean(ev(f, TRAIN))['NDCG@10']
                if best is None or m > best[0]:
                    best = (m, tau, beta, lam, P)
        m, tau, beta, lam, P = best
        chosen[name] = {'tau': tau, 'beta': beta, 'lambda': lam, 'train_NDCG@10': round(m, 4)}
        runs[f'Dense+{name}'] = fuse({q: dense[q] for q in TEST}, P, lam)
        # 罪名预测（测试查询，金标罪名限于 100 个候选罪名）
        hit1 = r3 = 0
        for q in TEST:
            g = set(qchg[q]) & set(CHARGES)
            rk = sorted(P[q], key=lambda c: -P[q][c])
            hit1 += rk[0] in g
            r3 += len(set(rk[:3]) & g) / max(1, len(g))
        cpred[name] = {'Hit@1': hit1 / len(TEST), 'R@3': r3 / len(TEST)}
    oracle = {q: {c: 1 / len(qchg[q]) for c in qchg[q]} for q in TEST}
    runs['Dense+ORACLE(gold charges)'] = fuse({q: dense[q] for q in TEST}, oracle, chosen['LRML']['lambda'] or .3)
    print('hyper-parameters chosen on train:', json.dumps(chosen, ensure_ascii=False))

    per = {n: ev(r, TEST) for n, r in runs.items()}
    res = {'n_test': len(TEST), 'n_train': len(TRAIN), 'chosen': chosen, 'charge_prediction': cpred,
           'test': {n: mean(p) for n, p in per.items()}, 'sig': {}}
    for n in runs:
        if n != 'Dense(fact)':
            res['sig'][n] = {m: randomization(per['Dense(fact)'], per[n], m) for m in ('NDCG@10', 'NDCG@30', 'R@30', 'MRR')}
    res['sig']['LRML vs STAT'] = {m: randomization(per['Dense+STAT'], per['Dense+LRML'], m) for m in ('NDCG@10', 'NDCG@30')}
    res['sig']['LRML vs JUREX'] = {m: randomization(per['Dense+JUREX'], per['Dense+LRML'], m) for m in ('NDCG@10', 'NDCG@30')}
    res['sig']['LRML+R vs LRML'] = {m: randomization(per['Dense+LRML'], per['Dense+LRML+R'], m) for m in ('NDCG@10', 'NDCG@30')}
    json.dump(res, open(os.path.join(HERE, 'results/crim_results.json'), 'w'), ensure_ascii=False, indent=1)
    keys = ['NDCG@10', 'NDCG@30', 'R@1', 'R@5', 'R@10', 'R@30', 'MRR']
    print(f"{'method':28s}" + ''.join(f'{k:>9s}' for k in keys))
    for n, m in res['test'].items():
        print(f'{n:28s}' + ''.join(f'{m[k]:9.4f}' for k in keys))
    print('charge prediction:', json.dumps(cpred))
    for n, s in res['sig'].items():
        print(f'  {n:30s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.4f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    os.makedirs(os.path.join(HERE, 'results'), exist_ok=True)
    main()
