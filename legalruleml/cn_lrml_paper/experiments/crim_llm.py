#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 A（续）：用已缓存的 qwen-plus 输出（不再调用 API）。

  FET      JUREX-4E 的 BGE+FET(Expert)：S = 0.7·S_fact + 0.3·S_FET（原始余弦，JUREX-4E §8.2）
  +CHG     查询罪名 = LLM 预测（lcr_jurex/llm_cache/predict）；sig = |C_d ∩ Ĉ_q| / |Ĉ_q|
  +CHG+R   Ĉ_q 再沿 LRML 罪名关系（relatedOffence）扩展，关联罪名权重 β = 0.5：sig = max_{c∈C_d} w(c)
  +ORACLE  Ĉ_q = 金标罪名（上界）
融合：score = minmax(base) + λ·sig，λ = 0.1（crim_run.py 在训练查询上为罪名信号选出的值；本脚本不在测试集上调参），β 事先固定。
用法：~/.venvs/lcr_jurex/bin/python crim_llm.py
"""
import json, os, re
from retrieval_lib import embed, minmax, metrics, mean, randomization, HERE
import crim_run as C

LCR = C.LCR
LAM, BETA = 0.1, 0.5


# ---- 与 lcr_jurex/build_runs.py 相同的解析（复制，以免导入时读取 API 配置）
def parse_json(raw):
    s = raw
    if '```' in s:
        s = s.split('```json')[-1] if '```json' in s else s.split('```')[1]
        s = s.split('```')[0]
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for m in re.finditer(r'"犯罪的四要件"\s*:\s*(\{[^{}]*\})', raw):
        try:
            f = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        rest = raw[m.end():m.end() + 600].split('"犯罪的四要件"')[0]
        name = re.search(r'"罪名"\s*:\s*"([^"]*)"', rest)
        out.append({'犯罪的四要件': f, '罪名': name.group(1) if name else ''})
    return out or None


def items(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    if isinstance(d, dict):
        if '犯罪的四要件' in d:
            return [d]
        return [v for v in d.values() if isinstance(v, dict)]
    return []


def fet_text(d):
    crime, crime2 = '', '\t罪名:'
    for i, it in enumerate(items(d), 1):
        f = it.get('犯罪的四要件', {})
        if isinstance(f, dict):
            crime += f'\t罪名{i}: ' + ', '.join(f'{k}: {v}' for k, v in f.items())
        crime2 += f"{it.get('罪名', '')}\t"
    return crime + crime2 if crime else ''


def load(step):
    p = os.path.join(LCR, 'llm_cache', step)
    return {f[:-5]: json.load(open(f'{p}/{f}', encoding='utf-8'))['output'] for f in os.listdir(p)}


def norm_charge(name):
    if name in C.CHARGES:
        return name
    for c in C.CHARGES:
        if name.rstrip('罪') and (name.rstrip('罪') in c or c.rstrip('罪') in name):
            return c
    return None


def main():
    TEST = C.TEST
    fet = load('fet_expert_qwen-plus')
    q_fet = {q: fet_text(parse_json(fet[f'q{q}']) or {}) or ''.join(C.qsent[q]) for q in TEST}
    c_fet = {p: fet_text(parse_json(fet[f'c{p}']) or {}) or ''.join(C.psent[p]) for p in C.psent}
    n_fail = sum(1 for p in C.psent if not fet_text(parse_json(fet[f'c{p}']) or {}))
    _, Xf = embed(q_fet, max_len=8192, bs=4)
    pids, Cf = embed(c_fet, max_len=8192, bs=4)
    _, Xq = embed({q: ''.join(C.qsent[q]) for q in TEST + C.TRAIN}, max_len=8192, bs=4)
    _, Cq = embed({p: ''.join(C.psent[p]) for p in C.psent}, max_len=8192, bs=4)
    Sfact = Xq[:len(TEST)] @ Cq.T
    Sfet = Xf @ Cf.T
    dense = {q: {p: float(Sfact[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(TEST)}
    fetr = {q: {p: float(.7 * Sfact[i, j] + .3 * Sfet[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(TEST)}

    pred = load('predict')
    Chat = {}
    for q in TEST:
        names = [x.strip('、，, ') for x in re.findall(r'[^，,;；\s]+?罪', pred[f'q{q}'])]
        Chat[q] = {c for c in map(norm_charge, names) if c}
    R = C.relations()
    hit1 = sum(1 for q in TEST if Chat[q] & set(C.qchg[q])) / len(TEST)

    def sig_run(base, weights):
        out = {}
        for q, s in base.items():
            s = minmax(s); w = weights[q]
            out[q] = {d: v + LAM * max([w.get(c, 0) for c in C.pchg.get(d, [])] or [0]) for d, v in s.items()}
        return out

    w_pred = {q: {c: 1.0 for c in Chat[q]} for q in TEST}
    w_rel = {}
    for q in TEST:
        w = {d: BETA for c in Chat[q] for d in R.get(c, ())}
        w.update({c: 1.0 for c in Chat[q]})
        w_rel[q] = w
    w_orc = {q: {c: 1.0 for c in C.qchg[q]} for q in TEST}
    runs = {'Dense(fact)': dense, 'Dense+CHG(LLM)': sig_run(dense, w_pred), 'Dense+CHG(LLM)+LRML-R': sig_run(dense, w_rel),
            'FET(Expert) [JUREX-4E]': fetr, 'FET+CHG(LLM)': sig_run(fetr, w_pred), 'FET+CHG(LLM)+LRML-R': sig_run(fetr, w_rel),
            'FET+ORACLE': sig_run(fetr, w_orc)}
    per = {n: {q: metrics(r[q], C.REL[q], **C.KS) for q in TEST} for n, r in runs.items()}
    res = {'lambda': LAM, 'beta': BETA, 'llm_charge_hit_any': hit1, 'fet_parse_failures': n_fail,
           'mean_pred_charges': sum(map(len, Chat.values())) / len(TEST),
           'mean_related_added': sum(len(w_rel[q]) - len(w_pred[q]) for q in TEST) / len(TEST),
           'test': {n: mean(p) for n, p in per.items()}, 'sig': {}}
    pairs = [('Dense(fact)', 'Dense+CHG(LLM)'), ('Dense+CHG(LLM)', 'Dense+CHG(LLM)+LRML-R'), ('Dense(fact)', 'FET(Expert) [JUREX-4E]'),
             ('FET(Expert) [JUREX-4E]', 'FET+CHG(LLM)'), ('FET+CHG(LLM)', 'FET+CHG(LLM)+LRML-R'), ('FET(Expert) [JUREX-4E]', 'FET+CHG(LLM)+LRML-R'),
             ('Dense(fact)', 'FET+CHG(LLM)+LRML-R'), ('FET(Expert) [JUREX-4E]', 'FET+ORACLE')]
    for a, b in pairs:
        res['sig'][f'{b} vs {a}'] = {m: randomization(per[a], per[b], m) for m in ('NDCG@10', 'NDCG@30', 'R@30')}
    json.dump(res, open(os.path.join(HERE, 'results/crim_llm_results.json'), 'w'), ensure_ascii=False, indent=1)
    keys = ['NDCG@10', 'NDCG@30', 'R@1', 'R@5', 'R@10', 'R@30', 'MRR']
    print(f"LLM charge prediction hits a gold charge on {hit1:.3f} of queries; mean predicted {res['mean_pred_charges']:.2f}, "
          f"related added {res['mean_related_added']:.2f}; FET parse failures {n_fail}")
    print(f"{'method':28s}" + ''.join(f'{k:>9s}' for k in keys))
    for n, m in res['test'].items():
        print(f'{n:28s}' + ''.join(f'{m[k]:9.4f}' for k in keys))
    for n, s in res['sig'].items():
        print(f'  {n:55s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.4f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    main()
