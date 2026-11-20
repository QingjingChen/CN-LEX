#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 A（全量）：罪名知识 = JUREX-4E 四要件 LegalRuleML（crim_jurex.lrml 结构层全树）+ crim_graph 四要件；
罪名关系 = crim_graph（此罪与彼罪 / 转化）∪ crim_jurex（规则抽取的转化 / 竞合）。

  嵌入式罪名信号（与 crim_run.py 相同的融合，λ τ β 在 599 个训练查询上选）：
      JUREX-top（原来的行）/ JUREX-full（全树）/ MERGED（全树 + crim_graph）；关系 = 合并关系
  LLM 预测罪名（与 crim_llm.py 相同，λ=0.1、β=0.5 事先固定）：关系 = crim_graph / 合并
用法：~/.venvs/lcr_jurex/bin/python crim_full_run.py
"""
import itertools, json, os, re
import numpy as np
from retrieval_lib import embed, minmax, metrics, mean, randomization, HERE
import crim_run as C
import crim_llm as CL

G = json.load(open(os.path.join(HERE, '../lrml/crim_jurex_glossary.json'), encoding='utf-8'))
J = {list(x)[0]: list(x.values())[0] for x in json.load(open(os.path.join(C.LCR, 'data/jurex/jurex4e.json'), encoding='utf-8'))}
FET = ('犯罪客体', '客观方面', '犯罪主体', '主观方面')


def flat(nodes):
    for n in nodes or []:
        yield re.sub(r'【[TF]?\d{2}/[^】；]*[；】]?', '', n.get('title', ''))
        yield from flat(n.get('topics'))


def jurex_full(c):
    f = J.get(c)
    if not f:
        return C.stat_text(c)
    return c + '。' + ''.join(f'{k}：' + '；'.join(flat(f.get(k)))[:400] + '。' for k in FET)


def merged(c):
    a = jurex_full(c) if c in J else ''
    b = C.lrml_text(c) if c in C.kb else ''
    return (a + '\n' + b).strip() or C.stat_text(c)


def relations():
    R = C.relations()
    n_cg = sum(map(len, R.values())) // 2
    for r in G['relations']:
        a, b = r['from'], r['to']
        if a in R and b in R and a != b:
            R[a].add(b); R[b].add(a)
    return R, n_cg, sum(map(len, R.values())) // 2


def main():
    TEST, TRAIN = C.TEST, C.TRAIN
    qids = TEST + TRAIN
    _, Xq = embed({q: ''.join(C.qsent[q]) for q in qids}, max_len=8192, bs=4)
    pids, Xc = embed({p: ''.join(C.psent[p]) for p in C.psent}, max_len=8192, bs=4)
    S = Xq @ Xc.T
    dense = {q: {p: float(S[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(qids)}
    R_cg = C.relations()
    R_all, n_cg, n_all = relations()
    print(f'relation pairs among GEAR charges: crim_graph {n_cg}, merged {n_all}')
    runs, chosen, cpred = {'Dense(fact)': {q: dense[q] for q in TEST}}, {}, {}
    for name, rep in (('JUREX-top', C.jurex_text), ('JUREX-full', jurex_full), ('MERGED', merged)):
        best = None
        for tau, beta in itertools.product((.02, .05, .1), (0, .25, .5, 1.0)):
            P = C.propagate(C.charge_probs(Xq, qids, rep, tau), R_all, beta)
            for lam in (0, .05, .1, .2, .3, .5):
                m = mean(C.ev(C.fuse({q: dense[q] for q in TRAIN}, P, lam), TRAIN))['NDCG@10']
                if best is None or m > best[0]:
                    best = (m, tau, beta, lam, P)
        m, tau, beta, lam, P = best
        chosen[name] = {'tau': tau, 'beta': beta, 'lambda': lam, 'train_NDCG@10': round(m, 4)}
        runs[f'Dense+{name}(+R)'] = C.fuse({q: dense[q] for q in TEST}, P, lam)
        h1 = sum(max(P[q], key=P[q].get) in C.qchg[q] for q in TEST) / len(TEST)
        cpred[name] = h1
    # ---- LLM 预测罪名
    pred = CL.load('predict')
    Chat = {q: {c for c in map(CL.norm_charge, [x.strip('、，, ') for x in re.findall(r'[^，,;；\s]+?罪', pred[f'q{q}'])]) if c} for q in TEST}
    fet = CL.load('fet_expert_qwen-plus')
    q_fet = {q: CL.fet_text(CL.parse_json(fet[f'q{q}']) or {}) or ''.join(C.qsent[q]) for q in TEST}
    c_fet = {p: CL.fet_text(CL.parse_json(fet[f'c{p}']) or {}) or ''.join(C.psent[p]) for p in C.psent}
    _, Xf = embed(q_fet, max_len=8192, bs=4)
    _, Cf = embed(c_fet, max_len=8192, bs=4)
    Sf = Xf @ Cf.T
    fetr = {q: {p: float(.7 * S[i, j] + .3 * Sf[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(TEST)}

    def sig_run(base, R):
        out = {}
        for q, s in base.items():
            s = minmax(s)
            w = {d: CL.BETA for c in Chat[q] for d in (R.get(c, ()) if R else ())}
            w.update({c: 1.0 for c in Chat[q]})
            out[q] = {d: v + CL.LAM * max([w.get(c, 0) for c in C.pchg.get(d, [])] or [0]) for d, v in s.items()}
        return out
    for bname, base in (('Dense', {q: dense[q] for q in TEST}), ('FET', fetr)):
        runs[f'{bname}+CHG(LLM)'] = sig_run(base, None)
        runs[f'{bname}+CHG(LLM)+R(crim_graph)'] = sig_run(base, R_cg)
        runs[f'{bname}+CHG(LLM)+R(merged)'] = sig_run(base, R_all)
    runs['FET [JUREX-4E]'] = fetr
    per = {n: {q: metrics(r[q], C.REL[q], **C.KS) for q in TEST} for n, r in runs.items()}
    res = {'chosen': chosen, 'charge_hit1_embedding': cpred, 'relations': {'crim_graph': n_cg, 'merged': n_all},
           'test': {n: mean(p) for n, p in per.items()}, 'sig': {}}
    for a, b in [('Dense(fact)', 'Dense+JUREX-top(+R)'), ('Dense+JUREX-top(+R)', 'Dense+JUREX-full(+R)'), ('Dense+JUREX-top(+R)', 'Dense+MERGED(+R)'),
                 ('Dense(fact)', 'Dense+MERGED(+R)'), ('FET+CHG(LLM)', 'FET+CHG(LLM)+R(crim_graph)'), ('FET+CHG(LLM)', 'FET+CHG(LLM)+R(merged)'),
                 ('FET [JUREX-4E]', 'FET+CHG(LLM)+R(merged)'), ('Dense(fact)', 'FET+CHG(LLM)+R(merged)')]:
        res['sig'][f'{b} vs {a}'] = {m: randomization(per[a], per[b], m) for m in ('NDCG@10', 'NDCG@30', 'R@30')}
    json.dump(res, open(os.path.join(HERE, 'results/crim_full_results.json'), 'w'), ensure_ascii=False, indent=1)
    print('chosen on train:', json.dumps(chosen, ensure_ascii=False)); print('charge Hit@1 (embedding):', cpred)
    keys = ['NDCG@10', 'NDCG@30', 'R@10', 'R@30', 'MRR']
    print(f"{'method':34s}" + ''.join(f'{k:>9s}' for k in keys))
    for n, m in res['test'].items():
        print(f'{n:34s}' + ''.join(f'{m[k]:9.4f}' for k in keys))
    for n, s in res['sig'].items():
        print(f'  {n:58s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.3f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    main()
