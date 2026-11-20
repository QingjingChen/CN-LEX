#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 E：易混淆罪名区分（Similar Charge Disambiguation, SCD；JUREX-4E 第 7 节的任务）。

数据：GCI（Liu et al., NAACL 2021）data.json（取自 CAIL2018），五个易混淆罪名组：
  F-E 诈骗 / 敲诈勒索；E-MPF 贪污 / 挪用公款；AP-DD 滥用职权 / 玩忽职守（JUREX-4E 使用的三组）；
  II-M-N 故意伤害 / 故意杀人 / 过失致人死亡；R-K-S 抢劫 / 绑架 / 抢夺。
每个罪名随机抽 40 个单罪名案件（seed 0），共 480 个；事实截断到 1,500 字。
条件（qwen3.5-35b-a3b，temperature 0）：
  S0 只给事实；S1 + 候选罪名的《刑法》条文；S2 + JUREX-4E 专家四要件（JUREX-4E 的设定）；
  S3 + CLeXML 规则（criminal_review.lrml 中以候选罪名条文为来源的规则，按与事实的相似度每罪名至多 6 条）；
  S4 S3 + CLeXML 推理结果（条件逐项核验 + 推理机求值，同 clexml_reason_qa.py）。
另报“推理机自身判定”：恰有一个候选罪名有适用规则时取该罪名，否则不判定。
指标：每组 Accuracy、Macro-F1；配对符号检验（S3 vs S2、S4 vs S3 等）。
用法：~/.venvs/lcr_jurex/bin/python scd_clexml.py [--per 40] [--workers 8]
"""
import argparse, collections, json, os, random, re
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from retrieval_lib import embed, HERE
import fakao_crim_qa as Q0
import clexml_reason_qa as CX

LCR = os.path.join(HERE, '../../lcr_jurex/data')
GROUPS = {'F-E': ['诈骗', '敲诈勒索'], 'E-MPF': ['贪污', '挪用公款'], 'AP-DD': ['滥用职权', '玩忽职守'],
          'II-M-N': ['故意伤害', '故意杀人', '过失致人死亡'], 'R-K-S': ['抢劫', '绑架', '抢夺']}
CONDS = ('S0', 'S1', 'S2', 'S3', 'S4')
WANTED = {c for cs in GROUPS.values() for c in cs}
C2A = json.load(open(f'{LCR}/jurex/crime2article.json', encoding='utf-8'))
J = {list(x)[0]: list(x.values())[0] for x in json.load(open(f'{LCR}/jurex/jurex4e.json', encoding='utf-8'))}
FET = ('犯罪客体', '客观方面', '犯罪主体', '主观方面')
ASK = """请判断下列案件事实应当认定为哪一个罪名。候选罪名只有：{cands}。
{materials}
【案件事实】
{fact}

先用不超过 150 字说明区分的关键要件（客体、客观行为、主体、主观罪过），最后一行只写“【罪名】：”加一个候选罪名（如“【罪名】：{first}罪”）。"""


def sample(per, seed=0):
    by = collections.defaultdict(list)
    for l in open(f'{LCR}/gci/data.json', encoding='utf-8'):
        r = json.loads(l)
        if len(r['accusation']) == 1 and r['accusation'][0] in WANTED:      # 只保留五组罪名，避免把 15 万条事实读进内存
            by[r['accusation'][0]].append(r['fact'])
    out = []
    for g, cs in GROUPS.items():
        for c in cs:
            for i, f in enumerate(random.Random(seed).sample(by[c], per)):
                out.append({'id': f'{g}-{c}-{i}', 'group': g, 'gold': c, 'fact': f[:1500]})
    return out


def statute(c):
    return '\n'.join(f"{c}罪：{Q0.art_text(str(a))}" for a in C2A.get(c, []) if str(a) in Q0.LAW)


def expert(c):
    f = J.get(c + '罪')
    return f"{c}罪：" + ''.join(f'{k}：' + '；'.join(t['title'] for t in f.get(k, [])) + '。' for k in FET) if f else statute(c)


def parse(raw, cands):
    tail = raw.split('【罪名】')[-1]
    hit = [c for c in sorted(cands, key=len, reverse=True) if c in tail]
    return hit[0] if hit else ''


def macro_f1(golds, preds, labels):
    f = []
    for l in labels:
        tp = sum(g == l and p == l for g, p in zip(golds, preds)); fp = sum(g != l and p == l for g, p in zip(golds, preds))
        fn = sum(g == l and p != l for g, p in zip(golds, preds))
        f.append(0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--per', type=int, default=40); ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--model', default='qwen3.5-35b-a3b'); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    data = sample(a.per); data = data[:a.limit] if a.limit else data
    RB = CX.Rules(os.path.join(HERE, '../lrml/criminal_review.lrml'))
    rk = list(RB.rules)
    _, RE = embed({k: (RB.rules[k]['note'] or k) for k in rk}, max_len=512, bs=32)
    _, FX = embed({x['id']: x['fact'] for x in data}, max_len=1024, bs=16)
    S = FX @ RE.T
    subs = {}
    for i, x in enumerate(data):
        sim = dict(zip(rk, map(float, S[i])))
        rules, ids, seen = [], {}, set()
        for c in GROUPS[x['group']]:
            arts = [str(a) for a in C2A.get(c, [])]
            cand = sorted({k for ar in arts for k in RB.by_art.get(ar, [])} - seen, key=lambda k: -sim[k])[:6]
            seen |= set(cand)
            for k in cand:
                r = RB.rules[k]; lv = CX.leaves(r['body'], k, [])
                for lid, _, el in lv:
                    ids[id(el)] = lid
                rules.append({'key': k, 'charge': c, 'articles': r['articles'], 'note': r['note'], 'leaves': [(lid, s) for lid, s, _ in lv],
                              'text': f"规则 {k}（{c}罪，第{'、'.join(r['articles'])}条）：{r['note']}\n  如果 {CX.render(r['body'], ids)}\n  则 {CX.head_str(r['then'])}"})
        subs[x['id']] = (rules, ids)

    def check(x):
        rules, _ = subs[x['id']]
        if not rules:
            return x['id'], {}
        raw = Q0.chat(CX.CHECK.format(rules='\n'.join(r['text'] for r in rules), question=x['fact']), model=a.model,
                      system='你是严谨的法律事实核验助手，只输出 JSON。', max_tokens=3000, seed=7)
        m = re.search(r'\{.*\}', raw, re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
            return x['id'], d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            return x['id'], {}
    with ThreadPoolExecutor(a.workers) as ex:
        checks = dict(ex.map(check, data))
    traces, rdec = {}, {}
    for x in data:
        rules, ids = subs[x['id']]
        traces[x['id']] = CX.reason(RB, rules, ids, checks[x['id']], x['fact']) if rules else ('', {}, 0, 0)
        # 推理机自身判定：哪些候选罪名至少有一条“适用”规则
        st = {}
        elem = {lid: el for r in rules for lid, _, el in CX.leaves(RB.rules[r['key']]['body'], r['key'], [])}
        val = {}
        qn = CX.norm(x['fact'])
        for lid, el in elem.items():
            c = CX.as_check(checks[x['id']].get(lid))
            v = {'成立': 'T', '不成立': 'F'}.get(c.get('v'), 'U')
            if v != 'U' and not (c.get('q') and len(CX.norm(c['q'])) >= 4 and CX.norm(c['q']) in qn):
                v = 'U'
            val[id(el)] = v
        app = {r['charge'] for r in rules if CX.evaluate_rule(RB.rules[r['key']]['body'], val) == 'T'}
        rdec[x['id']] = next(iter(app)) if len(app) == 1 else ''

    def ask(job):
        x, c = job
        cands = GROUPS[x['group']]
        mat = ''
        if c == 'S1':
            mat = '\n【法条】\n' + '\n'.join(statute(k) for k in cands) + '\n'
        elif c == 'S2':
            mat = '\n【专家四要件】\n' + '\n'.join(expert(k) for k in cands) + '\n'
        elif c in ('S3', 'S4'):
            rules = subs[x['id']][0]
            mat = '\n【CLeXML 规则】（审核版规则，可能不完整）\n' + '\n'.join(r['text'] for r in rules) + '\n'
            if c == 'S4':
                mat += ('\n【CLeXML 推理结果】（规则为待专家审核的草稿；条件由模型逐项核验后由推理机求值。“适用”只表示该规则的条件在事实中都能找到依据）\n'
                        + traces[x['id']][0] + '\n')
        p = ASK.format(cands='、'.join(k + '罪' for k in cands), materials=mat, fact=x['fact'], first=cands[0])
        try:
            raw = Q0.chat(p, model=a.model, system='你是严谨的中国刑法罪名认定助手。', max_tokens=1500, seed=7)
        except Exception as e:  # noqa: BLE001
            raw = f'ERROR {e}'
        return x['id'], c, parse(raw, cands), raw
    with ThreadPoolExecutor(a.workers) as ex:
        out = list(ex.map(ask, [(x, c) for x in data for c in CONDS]))
    pred = collections.defaultdict(dict); raws = collections.defaultdict(dict)
    for i, c, p, raw in out:
        pred[i][c] = p; raws[i][c] = raw
    res = {'n': len(data), 'per_charge': a.per, 'groups': {}, 'sign': {}, 'reasoner_only': {}}
    for g, cs in list(GROUPS.items()) + [('ALL', None)]:
        X = [x for x in data if g == 'ALL' or x['group'] == g]
        if not X:
            continue
        res['groups'][g] = {'n': len(X)}
        for c in CONDS:
            gs = [x['gold'] for x in X]; ps = [pred[x['id']][c] for x in X]
            labels = cs or sorted({x['gold'] for x in X})
            res['groups'][g][c] = {'Acc': float(np.mean([p == q for p, q in zip(ps, gs)])), 'MacroF1': macro_f1(gs, ps, labels)}
        dec = [x for x in X if rdec[x['id']]]
        res['reasoner_only'][g] = {'decided': len(dec), 'coverage': len(dec) / len(X),
                                   'acc_on_decided': float(np.mean([rdec[x['id']] == x['gold'] for x in dec])) if dec else None}
        acc = {c: [float(pred[x['id']][c] == x['gold']) for x in X] for c in CONDS}
        res['sign'][g] = {f'{y} vs {z}': Q0.sign_test(acc[z], acc[y]) for z, y in (('S0', 'S1'), ('S1', 'S2'), ('S2', 'S3'), ('S1', 'S3'), ('S3', 'S4'), ('S2', 'S4'))}
    st = collections.Counter(); judged = quoted = 0
    for x in data:
        st.update(traces[x['id']][1]); judged += traces[x['id']][2]; quoted += traces[x['id']][3]
    res['reasoning'] = {'mean_rules': float(np.mean([len(subs[x['id']][0]) for x in data])), 'rule_status': dict(st),
                        'proof_validity': quoted / judged if judged else None, 'unparsed': {c: sum(pred[x['id']][c] == '' for x in data) for c in CONDS}}
    tag = f"{a.model}{'_limit' + str(a.limit) if a.limit else ''}"
    with open(os.path.join(HERE, f'results/scd_clexml_{tag}.jsonl'), 'w', encoding='utf-8') as f:
        for x in data:
            f.write(json.dumps({'id': x['id'], 'group': x['group'], 'gold': x['gold'], 'pred': pred[x['id']], 'reasoner': rdec[x['id']],
                                'rules': [r['key'] for r in subs[x['id']][0]], 'trace': traces[x['id']][0], 'raw': raws[x['id']]},
                               ensure_ascii=False) + '\n')
    json.dump(res, open(os.path.join(HERE, f'results/scd_clexml_{tag}_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
