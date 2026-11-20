#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 A2：CAIL2018 罪名预测（exercise_contest 测试集随机 2,000 条，seed 0），202 个罪名。

零样本：用 BGE-m3 计算 案情事实 与 罪名表示 的余弦，对 202 个罪名排序。只改变罪名表示：
  NAME        罪名
  STAT        罪名 + 《刑法》条文（训练集中该罪名最常见的 relevant_article）
  JUREX-top   罪名 + JUREX-4E 四要件顶层标题                              （未覆盖的罪名回退到 STAT，下同）
  LRML-full   罪名 + crim_jurex.lrml 结构层（四要件完整专家标注树）
  LRML-formal 罪名 + crim_jurex.lrml 规则层的形式化要件（主体类型 / 年龄 / 单位、罪过形式 / 明知 / 目的、数额情节门槛、出罪情形）
  LRML-both   LRML-full + LRML-formal
少样本参考：每个罪名取训练集 5 个单罪名案件的事实嵌入均值作原型（PROTO-5）；融合 PROTO-5 + w·表示，w 在验证集 1,000 条上选。
指标：Acc@1（第一名属于金标罪名）、Hit@3、Hit@5、MRR；另报“全部金标罪名都被 JUREX-LRML 覆盖”的子集。
用法：~/.venvs/lcr_jurex/bin/python cail_charge_pred.py
"""
import collections, json, os, random, re
import numpy as np
import xml.etree.ElementTree as etree
from retrieval_lib import embed, randomization, HERE

LR = os.path.join(HERE, '../..')
D = os.path.join(LR, 'lcr_jurex/data/cail2018')
key = lambda s: re.sub(r'[\[\]、，,罪\s]', '', s)
norm = lambda s: re.sub(r'[\[\]]', '', s) + '罪'


def load(split):
    return [json.loads(l) for l in open(f'{D}/exercise_contest_{split}.jsonl', encoding='utf-8')]


# CAIL 数据只在本实验的 main() 中加载：其他脚本（QA、SCD）导入本模块时不应把 20 万条案件读进内存。
TRAIN = VALID = TEST = None
CHARGES = []


def ensure_data():
    global TRAIN, VALID, TEST, CHARGES
    if TRAIN is None:
        TRAIN, VALID, TEST = load('train'), load('valid'), load('test')
        CHARGES[:] = sorted({a for x in TRAIN + TEST for a in x['accusation']})


law = json.load(open(os.path.join(LR, 'crim_graph/law/criminal_law_2023.json'), encoding='utf-8'))
G = json.load(open(os.path.join(HERE, '../lrml/crim_jurex_glossary.json'), encoding='utf-8'))
JX = {key(v['name']): k for k, v in G['charges'].items()}
J = {list(x)[0]: list(x.values())[0] for x in json.load(open(os.path.join(LR, 'lcr_jurex/data/jurex/jurex4e.json'), encoding='utf-8'))}
FET = ('犯罪客体', '客观方面', '犯罪主体', '主观方面')

art_count = collections.defaultdict(collections.Counter)


def stat(c):
    if not art_count:                       # 第一次需要法条表示时才统计训练集
        ensure_data()
        for x in TRAIN:
            if len(x['accusation']) == 1:
                for a in x['relevant_articles']:
                    art_count[x['accusation'][0]][a] += 1
    arts = [a for a, _ in art_count[c].most_common(1)]
    return norm(c) + '。' + ''.join(''.join(law[str(a)]['paras']) for a in arts if str(a) in law)


def jx_name(c):
    k = JX.get(key(c))
    return G['charges'][k]['name'] if k else None


def jurex_top(c):
    n = jx_name(c)
    if not n:
        return stat(c)
    return norm(c) + '。' + ''.join(f'{e}：' + '；'.join(t['title'] for t in J[n].get(e, [])) + '。' for e in FET)


def flat(nodes):
    for t in nodes or []:
        yield re.sub(r'【[TF]?\d{2}/[^】；]*[；】]?', '', t.get('title', ''))
        yield from flat(t.get('topics'))


def lrml_full(c):
    n = jx_name(c)
    if not n:
        return stat(c)
    return norm(c) + '。' + ''.join(f'{e}：' + '；'.join(flat(J[n].get(e)))[:400] + '。' for e in FET)


# ---- 规则层形式化要件 → 紧凑文本
L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
R = '{http://ruleml.org/spec}'
SPECIAL = {'stateOrganStaff': '国家机关工作人员', 'stateFunctionary': '国家工作人员', 'judicialStaff': '司法工作人员', 'serviceman': '军人',
           'male': '男子', 'companyStaff': '公司、企业人员', 'postalStaff': '邮政工作人员', 'financialStaff': '金融机构工作人员',
           'dutyBearer': '负有特定义务的人', 'statutoryRole': '依法具有特定身份的人', 'other': '特殊主体'}
MENS = {'directIntent': '直接故意', 'intent': '故意', 'negligence': '过失'}
THR = {'amountExtremelyHuge': '数额特别巨大', 'amountHuge': '数额巨大', 'amountLarge': '数额较大', 'circumstancesExtremelySerious': '情节特别严重',
       'circumstancesSerious': '情节严重', 'circumstancesVile': '情节恶劣', 'seriousConsequence': '造成严重后果'}
FORMAL = collections.defaultdict(lambda: collections.defaultdict(list))
root = etree.parse(os.path.join(HERE, '../lrml/crim_jurex.lrml')).getroot()
PARENT = {c: p for p in root.iter() for c in p}


def under_naf(e):
    while e in PARENT:
        e = PARENT[e]
        if e.tag == R + 'Naf':
            return True
    return False


for st in root.iter(L + 'ConstitutiveStatement'):
    k = st.get('key'); m = re.match(r'jx-(c\d{3})-r-(sub|sa|oa|main)$', k)
    if not m:
        continue
    cid, part = m.groups()
    for at in st.find(R + 'Rule').find(R + 'if').iter(R + 'Atom'):
        rel = at.find(R + 'Rel').get('iri').split(':', 1)[1]
        args = [a.text for a in at if a.tag in (R + 'Ind', R + 'Var')]
        naf = under_naf(at)
        if rel == 'minAge': FORMAL[cid]['主体'].append(f"已满{args[1].replace('age', '')}周岁")
        elif rel == 'generalSubject': FORMAL[cid]['主体'].append('一般主体')
        elif rel == 'specialSubject': FORMAL[cid]['主体'].append('特殊主体：' + SPECIAL.get(args[1], args[1]))
        elif rel == 'unitSubject': FORMAL[cid]['主体'].append('单位可以构成')
        elif rel == 'mens': FORMAL[cid]['主观'].append(MENS[args[2]])
        elif rel == 'knowledge': FORMAL[cid]['主观'].append('明知')
        elif rel == 'purpose': FORMAL[cid]['主观'].append('以' + G['predicates'].get(args[2], args[2]) + '为目的')
        elif rel == 'threshold': FORMAL[cid]['客观'].append(THR[args[1]])
        elif naf: FORMAL[cid]['出罪'].append(G['predicates'].get(rel, '')[:40])


def lrml_formal(c, base=None):
    k = JX.get(key(c))
    if not k:
        return base or stat(c)
    f = FORMAL[k]
    s = '；'.join(f'{p}：' + '，'.join(dict.fromkeys(f[p])) for p in ('主体', '主观', '客观', '出罪') if f[p])
    return (base or norm(c)) + '。要件：' + s + '。'


REPS = {'NAME': lambda c: norm(c), 'STAT': stat, 'JUREX-top': jurex_top, 'LRML-full': lrml_full,
        'LRML-formal': lambda c: lrml_formal(c), 'LRML-both': lambda c: lrml_formal(c, lrml_full(c))}


def metrics(scores, gold):
    order = np.argsort(-scores)
    ranked = [CHARGES[i] for i in order]
    pos = next(i for i, c in enumerate(ranked) if c in gold)
    return {'Acc@1': float(pos == 0), 'Hit@3': float(pos < 3), 'Hit@5': float(pos < 5), 'MRR': 1 / (pos + 1)}


def mean(per, ids):
    return {m: float(np.mean([per[i][m] for i in ids])) for m in ('Acc@1', 'Hit@3', 'Hit@5', 'MRR')}


def main():
    ensure_data()
    rng = random.Random(0)
    test = rng.sample(TEST, 2000)
    valid = random.Random(1).sample(VALID, 1000)
    covered = [i for i, x in enumerate(test) if all(key(a) in JX for a in x['accusation'])]
    print(f'charges {len(CHARGES)} | test sample 2000, fully covered by JUREX-LRML {len(covered)}')
    _, Xt = embed({str(i): x['fact'] for i, x in enumerate(test)}, max_len=1024, bs=16)
    _, Xv = embed({str(i): x['fact'] for i, x in enumerate(valid)}, max_len=1024, bs=16)
    # 少样本原型
    by, by_any = collections.defaultdict(list), collections.defaultdict(list)
    for x in TRAIN:
        if len(x['accusation']) == 1:
            by[x['accusation'][0]].append(x['fact'])
        for a in x['accusation']:
            by_any[a].append(x['fact'])
    for c in CHARGES:                      # 没有单罪名案例的罪名，用包含该罪名的多罪名案例
        if len(by[c]) < 5:
            by[c] = (by[c] + [f for f in by_any[c] if f not in by[c]])[:max(5, len(by[c]))]
    print('charges without any training case:', [c for c in CHARGES if not by[c]])
    shots = {f'{c}#{j}': f for c in CHARGES for j, f in enumerate(random.Random(2).sample(by[c], min(5, len(by[c]))))}
    sid, S = embed(shots, max_len=1024, bs=16)
    P = np.stack([S[[i for i, s in enumerate(sid) if s.rsplit('#', 1)[0] == c]].mean(0) for c in CHARGES])
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    res = {'n': 2000, 'n_covered': len(covered), 'test': {}, 'covered': {}, 'fusion_w': {}, 'sig': {}}
    per_all = {}
    E = {}
    for name, rep in REPS.items():
        _, E[name] = embed({c: rep(c) for c in CHARGES}, max_len=2048, bs=8)
        per = [metrics(Xt[i] @ E[name].T, set(x['accusation'])) for i, x in enumerate(test)]
        per_all[name] = per
    per_all['PROTO-5'] = [metrics(Xt[i] @ P.T, set(x['accusation'])) for i, x in enumerate(test)]
    for name in ('STAT', 'LRML-full', 'LRML-both'):
        best = max((0, .05, .1, .25, .5, .75, 1.0, 1.5), key=lambda w: np.mean([metrics(Xv[i] @ P.T + w * (Xv[i] @ E[name].T), set(x['accusation']))['Acc@1']
                                                                        for i, x in enumerate(valid)]))
        res['fusion_w'][name] = best
        per_all[f'PROTO-5 + {name}'] = [metrics(Xt[i] @ P.T + best * (Xt[i] @ E[name].T), set(x['accusation'])) for i, x in enumerate(test)]
    ids = list(range(2000))
    for name, per in per_all.items():
        res['test'][name] = mean(per, ids); res['covered'][name] = mean(per, covered)
    tod = lambda per, ids_: {i: per[i] for i in ids_}
    for a, b in [('STAT', 'JUREX-top'), ('STAT', 'LRML-full'), ('JUREX-top', 'LRML-full'), ('LRML-full', 'LRML-both'), ('STAT', 'LRML-formal'),
                 ('PROTO-5', 'PROTO-5 + STAT'), ('PROTO-5', 'PROTO-5 + LRML-full'), ('PROTO-5 + STAT', 'PROTO-5 + LRML-full'), ('PROTO-5', 'PROTO-5 + LRML-both'), ('PROTO-5 + STAT', 'PROTO-5 + LRML-both')]:
        res['sig'][f'{b} vs {a} (covered)'] = {m: randomization(tod(per_all[a], covered), tod(per_all[b], covered), m) for m in ('Acc@1', 'Hit@3')}
    json.dump(res, open(os.path.join(HERE, 'results/cail_charge_results.json'), 'w'), ensure_ascii=False, indent=1)
    print('fusion weight on valid:', res['fusion_w'])
    print(f"{'representation':26s}{'Acc@1':>8s}{'Hit@3':>8s}{'Hit@5':>8s}{'MRR':>8s}   | covered({len(covered)}) Acc@1 Hit@3")
    for n in per_all:
        m, c = res['test'][n], res['covered'][n]
        print(f'{n:26s}' + ''.join(f'{m[k]:8.4f}' for k in ('Acc@1', 'Hit@3', 'Hit@5', 'MRR')) + f"   |  {c['Acc@1']:.4f} {c['Hit@3']:.4f}")
    for n, s in res['sig'].items():
        print(f'  {n:44s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.3f}' for m, (d, p) in s.items()))
    print('example LRML-formal:', REPS['LRML-formal']('盗窃'))


if __name__ == '__main__':
    main()
