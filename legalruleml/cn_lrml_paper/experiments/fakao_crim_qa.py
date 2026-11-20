#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 C：法考刑法客观题 QA（data/fakao_criminal_qa.jsonl，883 题）。

  C0  闭卷                     只给题目
  C1  + 法条                   BGE-m3 从《刑法》（2023 文本，505 条）检索前 5 条
  C2  + 法条 + LRML            C1 的法条 + 相关罪名的 LegalRuleML 规则（crim_jurex.lrml）：
                               题目中点名的罪名 + 按 LRML 表示检索的前 3 个罪名；每个罪名给出
                               对应条文、主体 / 主观 / 门槛 / 出罪情形（规则层形式化要件）、转化与竞合关系
模型：qwen3.5-35b-a3b（DashScope，temperature 0，seed 7，不开思考），与 LexReAct 实验相同；调用带磁盘缓存。
指标：EM（选项集合完全一致）、选项级 F1；配对符号检验。另报单选 / 多选、2021 年后（现行法）子集。
用法：~/.venvs/lcr_jurex/bin/python fakao_crim_qa.py [--limit 5] [--model ...] [--workers 8]
"""
import argparse, collections, json, math, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from retrieval_lib import embed, HERE
import cail_charge_pred as CP

ROOT = os.path.abspath(os.path.join(HERE, '../../..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts/smt'))
from llm_client import chat  # noqa: E402

QA = [json.loads(l) for l in open(os.path.join(HERE, '../data/fakao_criminal_qa.jsonl'), encoding='utf-8')]
LAW = CP.law
G = CP.G
NAMES = {v['name']: k for k, v in G['charges'].items()}
SYSTEM = '你是严谨的中国法律职业资格考试（刑法）答题助手。依据题目事实和刑法规定作答；如提供了参考材料，可以参考，但材料可能不完整或与题目无关，需自行判断。'


def qtext(q):
    return f"{q['question']}\nA. {q['A']}\nB. {q['B']}\nC. {q['C']}\nD. {q['D']}"


def art_text(a):
    return f"《刑法》{LAW[a]['label']}：" + ''.join(LAW[a]['paras'])


def charge_card(cid):
    c = G['charges'][cid]
    f = CP.FORMAL[cid]
    parts = [f"【{c['name']}】" + (('依据：' + '、'.join(f'第{a}条' for a in c['articles']) + '。') if c['articles'] else '')]
    for p in ('主体', '主观', '客观', '出罪'):
        if f[p]:
            parts.append(f'{p}：' + '，'.join(dict.fromkeys(x[:60] for x in f[p])) + '。')
    rel = [r for r in G['relations'] if r['from'] == c['name'] or r['to'] == c['name']]
    for r in rel[:3]:
        parts.append(('转化：' if r['type'] == 'conversion' else '竞合：') + f"{r['from']}→{r['to']}（{r['text'][:50]}）")
    return ''.join(parts)


def contexts():
    arts = list(LAW)
    _, A = embed({a: art_text(a) for a in arts}, max_len=1024, bs=16)
    _, X = embed({q['id']: qtext(q) for q in QA}, max_len=1024, bs=16)
    cids = list(G['charges'])
    _, C = embed({k: CP.REPS['LRML-both'](G['charges'][k]['name'].rstrip('罪')) for k in cids}, max_len=2048, bs=8)
    out = {}
    for i, q in enumerate(QA):
        top_a = [arts[j] for j in np.argsort(-(A @ X[i]))[:5]]
        named = [NAMES[n] for n in q['charges_mentioned'] if n in NAMES][:4]
        sim = [cids[j] for j in np.argsort(-(C @ X[i]))[:3]]
        chs = list(dict.fromkeys(named + sim))[:5]
        out[q['id']] = {'arts': top_a, 'charges': chs}
    return out


def prompt(q, cond, ctx):
    body = f"题目：\n{qtext(q)}\n"
    if cond in ('C1', 'C2'):
        body += '\n参考法条：\n' + '\n'.join(art_text(a) for a in ctx['arts']) + '\n'
    if cond == 'C2':
        body += '\n参考罪名规则（LegalRuleML 四要件规则，可能不完整）：\n' + '\n'.join(charge_card(c) for c in ctx['charges']) + '\n'
    body += '\n题目可能是单选或多选。请用不超过 200 字逐项简要分析，不要反复犹豫；最后一行只写“答案：”加选项字母（如“答案：AC”）。'
    return body


def parse(raw):
    m = re.findall(r'答案[:：]\s*([A-D、,，\s]+)', raw)
    if not m:
        return ''
    return ''.join(sorted(set(re.sub(r'[^A-D]', '', m[-1]))))


def score(pred, gold):
    g, p = set(gold), set(pred)
    em = float(g == p)
    if not p:
        return em, 0.0
    tp = len(g & p)
    f1 = 0.0 if tp == 0 else 2 * tp / (len(g) + len(p))
    return em, f1


def sign_test(a, b):
    """配对符号检验（双侧，正态近似 / 小样本精确）：b 比 a 好的题数 vs 差的题数。"""
    w = sum(1 for x, y in zip(a, b) if y > x); l = sum(1 for x, y in zip(a, b) if y < x); n = w + l
    if n == 0:
        return w, l, 1.0
    k = min(w, l)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n * 2
    return w, l, min(1.0, p)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--model', default='qwen3.5-35b-a3b'); ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    qs = QA[:a.limit] if a.limit else QA
    ctx = contexts()
    jobs = [(q, c) for q in qs for c in ('C0', 'C1', 'C2')]

    def run(job):
        q, c = job
        try:
            raw = chat(prompt(q, c, ctx[q['id']]), model=a.model, system=SYSTEM, max_tokens=3000, seed=7)
        except Exception as e:  # noqa: BLE001
            raw = f'ERROR {e}'
        return q['id'], c, raw
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(run, jobs))
    rows = collections.defaultdict(dict)
    for qid, c, raw in results:
        rows[qid][c] = {'raw': raw, 'pred': parse(raw)}
    out_path = os.path.join(HERE, f"results/fakao_qa_{a.model}{'_limit' + str(a.limit) if a.limit else ''}.jsonl")
    with open(out_path, 'w', encoding='utf-8') as f:
        for q in qs:
            f.write(json.dumps({'id': q['id'], 'year': q['year'], 'gold': q['answer'], 'multi': q['multi'], 'ctx': ctx[q['id']],
                                **{c: rows[q['id']][c] for c in ('C0', 'C1', 'C2')}}, ensure_ascii=False) + '\n')
    subsets = {'all': qs, 'single': [q for q in qs if not q['multi']], 'multi': [q for q in qs if q['multi']],
               'year>=2021': [q for q in qs if q['year'] >= 2021],
               'charge-in-LRML': [q for q in qs if any(n in NAMES for n in q['charges_mentioned'])]}
    res = {'model': a.model, 'n': len(qs), 'errors': sum(r['raw'].startswith('ERROR') for v in rows.values() for r in v.values()),
           'unparsed': sum(r['pred'] == '' for v in rows.values() for r in v.values()), 'subsets': {}, 'sign': {}}
    for name, sub in subsets.items():
        if not sub:
            continue
        res['subsets'][name] = {'n': len(sub)}
        for c in ('C0', 'C1', 'C2'):
            s = [score(rows[q['id']][c]['pred'], q['answer']) for q in sub]
            res['subsets'][name][c] = {'EM': float(np.mean([x[0] for x in s])), 'F1': float(np.mean([x[1] for x in s]))}
    em = {c: [score(rows[q['id']][c]['pred'], q['answer'])[0] for q in qs] for c in ('C0', 'C1', 'C2')}
    for x, y in (('C0', 'C1'), ('C1', 'C2'), ('C0', 'C2')):
        res['sign'][f'{y} vs {x}'] = sign_test(em[x], em[y])
    json.dump(res, open(out_path.replace('.jsonl', '_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
