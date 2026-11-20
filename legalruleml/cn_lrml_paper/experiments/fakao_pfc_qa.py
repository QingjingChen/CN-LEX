#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 C（修正版）：法考刑法客观题，P-F-C 思维链，无信息泄露。

修正：旧版 C2 的“题目点名罪名”来自 题干+选项+解析（charges_mentioned），解析信息因此进入了规则检索。
本版所有检索只用 题干+选项：点名罪名在题干和选项中匹配，相似罪名与法条都用 BGE-m3 以 题干+选项 为查询。
答题格式改为 LEGO 的 PFC-v3（Provision–Fact–Conclusion），只把民法的第 4、5 条要求换成刑法对应要求。
  P0  PFC，不给法条（依据模型自身的刑法知识）
  P1  PFC + 检索的《刑法》前 5 条
  P2  PFC + 同样的前 5 条 + CLeXML 罪名规则卡片（点名罪名 + 相似度前 3，规则层要件 / 出罪 / 转化与竞合）
模型 qwen3.5-35b-a3b，temperature 0，seed 7，不开思考；调用带磁盘缓存。
用法：~/.venvs/lcr_jurex/bin/python fakao_pfc_qa.py [--limit N] [--workers 8]
"""
import argparse, collections, json, os, re
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from retrieval_lib import embed, HERE
import fakao_crim_qa as Q0          # 复用：题目文本、法条文本、罪名规则卡片、计分、符号检验、LLM 客户端
import cail_charge_pred as CP

QA, LAW, G = Q0.QA, Q0.LAW, Q0.G
NAMES = sorted(Q0.NAMES, key=len, reverse=True)
SYSTEM = '你是严谨的中国刑法客观题助手。你必须严格基于题干事实、选项和给定材料推理，不得编造未给出的事实。'
PFC = """请使用 P/F/C（Provision-Fact-Conclusion）方法解答这道中国刑法客观题。

角色：站在中立裁判者/考试阅卷者立场。
要求：
1. 先用一句话明确本题要判断的法律对象和题目问法。
2. P-Provision：{p_rule}
3. P 阶段必须说明法条关系：一般规定/特别规定、但书或出罪情形、转化犯、想象竞合与法条竞合之间谁控制结论。
4. 特别注意区分：犯罪构成要件是否齐备、违法阻却（正当防卫、紧急避险）、责任阻却（年龄、精神状态）、犯罪形态（预备/未遂/中止/既遂）、共犯、罪数与量刑，不能把一种法律后果扩大成另一种。
5. 逐一核对罪名的四要件（客体、客观方面、主体、主观方面）；任何一个要件不满足，就不能认定构成该罪。
6. F-Fact：列出会影响判断的题干事实，不要写终局法律结论。
7. C-Conclusion：先做一次“法条关系校验”，再逐项判断 A/B/C/D 的选项命题是否成立。每个选项最多一句判断。
8. Conclusion 必须根据题目问法输出应选项；如果题干问“错误的是/不正确的是/不能成立的是”，应选择错误项。
9. 不要为了覆盖而多选；只有选项的主体、罪名、要件事实和法律后果都完整匹配时才选。
10. 每一段用 1-3 句，重点比较选项，不要长篇复述。
11. 最后一行必须且只能是 [正确答案]字母<eoa>，例如 [正确答案]A<eoa> 或 [正确答案]BD<eoa>。
{materials}
【题目】
{question}

请按以下格式输出：
判断对象:

P-Provision:
法条关系:

F-Fact:


C-Conclusion:
法条关系校验:

[正确答案]...<eoa>"""


def named_charges(q):
    """只在题干与选项中匹配罪名（最长优先，不读解析）。"""
    t = Q0.qtext(q); found = []
    for n in NAMES:
        if n in t:
            found.append(n); t = t.replace(n, '□')
    return found


def contexts():
    arts = list(LAW)
    _, A = embed({a: Q0.art_text(a) for a in arts}, max_len=1024, bs=16)
    _, X = embed({q['id']: Q0.qtext(q) for q in QA}, max_len=1024, bs=16)
    cids = list(G['charges'])
    _, C = embed({k: CP.REPS['LRML-both'](G['charges'][k]['name'].rstrip('罪')) for k in cids}, max_len=2048, bs=8)
    out = {}
    for i, q in enumerate(QA):
        named = [Q0.NAMES[n] for n in named_charges(q)][:4]
        sim = [cids[j] for j in np.argsort(-(C @ X[i]))[:3]]
        out[q['id']] = {'arts': [arts[j] for j in np.argsort(-(A @ X[i]))[:5]], 'charges': list(dict.fromkeys(named + sim))[:5],
                        'named': named}
    return out


def prompt(q, cond, ctx):
    if cond == 'P0':
        mat, rule = '', '本题未给出法条；依据你掌握的现行《刑法》列出控制本题的裁判规则，不要编造条文号。'
    else:
        mat = '\n【给定法条】\n' + '\n'.join(f'[{i + 1}] {Q0.art_text(a)}' for i, a in enumerate(ctx['arts'])) + '\n'
        rule = '只列出【给定法条】' + ('和【罪名规则】' if cond == 'P2' else '') + '中真正控制本题的裁判规则；材料可能不完整或与本题无关，需要自行判断。'
        if cond == 'P2':
            mat += '\n【罪名规则】（CLeXML 四要件规则，可能不完整）\n' + '\n'.join(Q0.charge_card(c) for c in ctx['charges']) + '\n'
    return PFC.format(p_rule=rule, materials=mat, question=Q0.qtext(q))


def parse(raw):
    m = re.findall(r'\[正确答案\]\s*([A-D、,，\s]+)\s*<eoa>', raw) or re.findall(r'\[正确答案\]\s*([A-D、,，\s]+)', raw)
    return ''.join(sorted(set(re.sub(r'[^A-D]', '', m[-1])))) if m else ''


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--model', default='qwen3.5-35b-a3b'); ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    qs = QA[:a.limit] if a.limit else QA
    ctx = contexts()
    conds = ('P0', 'P1', 'P2')

    def run(job):
        q, c = job
        try:
            raw = Q0.chat(prompt(q, c, ctx[q['id']]), model=a.model, system=SYSTEM, max_tokens=3000, seed=7)
        except Exception as e:  # noqa: BLE001
            raw = f'ERROR {e}'
        return q['id'], c, raw
    with ThreadPoolExecutor(a.workers) as ex:
        out = list(ex.map(run, [(q, c) for q in qs for c in conds]))
    rows = collections.defaultdict(dict)
    for qid, c, raw in out:
        rows[qid][c] = {'raw': raw, 'pred': parse(raw)}
    tag = f"{a.model}{'_limit' + str(a.limit) if a.limit else ''}"
    with open(os.path.join(HERE, f'results/fakao_pfc_{tag}.jsonl'), 'w', encoding='utf-8') as f:
        for q in qs:
            f.write(json.dumps({'id': q['id'], 'year': q['year'], 'gold': q['answer'], 'multi': q['multi'], 'ctx': ctx[q['id']],
                                **{c: rows[q['id']][c] for c in conds}}, ensure_ascii=False) + '\n')
    subsets = {'all': qs, 'single': [q for q in qs if not q['multi']], 'multi': [q for q in qs if q['multi']],
               'year>=2021': [q for q in qs if q['year'] >= 2021], 'named-charge': [q for q in qs if ctx[q['id']]['named']]}
    res = {'model': a.model, 'n': len(qs), 'leakage_fix': 'charges named only from stem+options; no explanation text in retrieval',
           'errors': sum(r['raw'].startswith('ERROR') for v in rows.values() for r in v.values()),
           'unparsed': {c: sum(rows[q['id']][c]['pred'] == '' for q in qs) for c in conds}, 'subsets': {}, 'sign': {}}
    for name, sub in subsets.items():
        if not sub:
            continue
        res['subsets'][name] = {'n': len(sub)}
        for c in conds:
            s = [Q0.score(rows[q['id']][c]['pred'], q['answer']) for q in sub]
            res['subsets'][name][c] = {'EM': float(np.mean([x[0] for x in s])), 'F1': float(np.mean([x[1] for x in s]))}
        em = {c: [Q0.score(rows[q['id']][c]['pred'], q['answer'])[0] for q in sub] for c in conds}
        res['sign'][name] = {f'{y} vs {x}': Q0.sign_test(em[x], em[y]) for x, y in (('P0', 'P1'), ('P1', 'P2'), ('P0', 'P2'))}
    json.dump(res, open(os.path.join(HERE, f'results/fakao_pfc_{tag}_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
