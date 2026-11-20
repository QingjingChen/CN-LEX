#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""要件表示的几种做法（事先确定，开发集选权重 / 选方案，测试集只报告）。

  E0  LEGO 卡片要件（论文现版本）                       作为独立特征：S = dense + w_e·要件相似度
  E1  CLeXML 规则要件，只保留中文说明（去掉英文谓词名）   同上
  E2  LEGO 卡片 + CLeXML 中文说明                         同上
  E3  文档扩展：条文原文 + CLeXML 中文说明，合在一起编码，替代 Dense 的条文向量
  E4  文档扩展：条文原文 + CLeXML 中文说明 + LEGO 卡片
每种再叠加语义网（有类型、有方向，开发集选权重）。显著性：配对随机化检验，10,000 次置换。
用法：OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python element_variants.py
"""
import sys, os, re, json, random, collections
import numpy as np
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../experiments'))
from retrieval_lib import embed
import minimal_retrieval as M

L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
R = '{http://ruleml.org/spec}'


def clexml_notes():
    """每条法条下 CLeXML 规则的中文说明（Comment 第一段），按文件顺序最多 6 条。"""
    root = ET.parse(f'{M.D}/civil_review.lrml').getroot()
    src = {}
    for e in root.iter(L + 'LegalSource'):
        m = re.search(r'#art_(\d+)', e.get('sameAs', ''))
        if m:
            src[e.get('key')] = m.group(1)
    arts = collections.defaultdict(set)
    for e in root.iter(L + 'Association'):
        A = {src[s.get('keyref', '').lstrip('#')] for s in e.findall(L + 'appliesSource') if s.get('keyref', '').lstrip('#') in src}
        for t in e.findall(L + 'toTarget'):
            arts[t.get('keyref').lstrip('#')] |= A
    per = collections.defaultdict(list)
    for tag in ('ConstitutiveStatement', 'PrescriptiveStatement'):
        for st in root.iter(L + tag):
            c = st.find(L + 'Comment')
            note = (c.text or '').split('CNLR_REVIEW_META:')[0].strip() if c is not None else ''
            if note:
                for a in arts.get(st.get('key'), ()):
                    if note not in per[a]:
                        per[a].append(note)
    return {a: '；'.join(v[:6]) for a, v in per.items()}


def vec(texts, ids, dim):
    keys = [a for a in ids if texts.get(a)]
    _, E = embed({a: texts[a] for a in keys}, max_len=1024, bs=16)
    out = np.zeros((len(ids), dim), dtype=np.float32); has = np.zeros(len(ids), dtype=bool)
    ix = {a: i for i, a in enumerate(keys)}
    for j, a in enumerate(ids):
        if a in ix:
            out[j] = E[ix[a]]; has[j] = True
    return out, has


def rnd(a, b, n=10000, seed=0):
    d = np.array(b) - np.array(a); obs = abs(d.sum()); rng = random.Random(seed)
    hit = sum(abs(sum(x if rng.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n))
    return float(d.mean()), (hit + 1) / (n + 1)


def per_query(Rt, qs, w):
    rs = [Rt.rank(q['qid'], w)[0] for q in qs]
    return ([M.recall_at_k(r, set(q['gold'])) for r, q in zip(rs, qs)], [M.ndcg_at_k(r, set(q['gold'])) for r, q in zip(rs, qs)])


def main():
    Q, A, XQ, XA, XE, has = M.load()
    ids = [a['id'] for a in A]; dim = XA.shape[1]
    G = M.read_graph(f'{M.D}/civil_review.lrml', set(ids))
    notes = clexml_notes()
    lego = {a['id']: a['element_text'] for a in A if a['element_text']}
    print('有 CLeXML 中文说明的条文', len(notes), '| 有 LEGO 卡片要件的条文', len(lego))
    E1, h1 = vec(notes, ids, dim)
    E2, h2 = vec({a: '\n'.join(x for x in (notes.get(a), lego.get(a)) if x) for a in ids}, ids, dim)
    doc3, _ = vec({a['id']: a['text'] + ('\n' + notes[a['id']] if a['id'] in notes else '') for a in A}, ids, dim)
    doc4, _ = vec({a['id']: a['text'] + ('\n' + notes[a['id']] if a['id'] in notes else '') + ('\n' + lego[a['id']] if a['id'] in lego else '') for a in A}, ids, dim)
    variants = {'E0 LEGO 卡片要件（特征）': (XA, XE, has), 'E1 CLeXML 中文说明（特征）': (XA, E1, h1),
                'E2 LEGO + CLeXML 说明（特征）': (XA, E2, h2), 'E3 文档扩展：原文 + CLeXML 说明': (doc3, XE, has),
                'E4 文档扩展：原文 + CLeXML 说明 + LEGO': (doc4, XE, has)}
    dev = [q for q in Q if q['split'] == 'dev']; test = [q for q in Q if q['split'] == 'test']
    base = per_query(M.Retriever(Q, A, XQ, XA, XE, has, G), test, {})
    res = {}
    print(f"\n{'方案':34s}{'开发 NDCG':>10s}{'测试 R@10':>10s}{'测试 NDCG':>10s}   相对 Dense（测试）")
    print(f"{'Dense（基线）':34s}{'':10s}{np.mean(base[0]):10.4f}{np.mean(base[1]):10.4f}")
    for name, (XAv, XEv, hv) in variants.items():
        Rt = M.Retriever(Q, A, XQ, XAv, XEv, hv, G)
        doc_exp = name.startswith('E3') or name.startswith('E4')
        w1 = {} if doc_exp else M.tune(Rt, dev, [])
        w2 = M.tune(Rt, dev, list(M.TYPES)) if not doc_exp else dict(M.tune(Rt, dev, list(M.TYPES)), elem=0)
        if doc_exp:   # 文档扩展本身就是新的 Dense；语义网照常叠加，不再加要件特征
            w2 = {'elem': 0}
            for _ in range(2):
                for t in M.TYPES:
                    w2[t] = max(M.GRID, key=lambda x: (M.evaluate(Rt, dev, dict(w2, **{t: x}))[1], -x))
        for tag, w in (('', w1), (' + 语义网', w2)):
            dv = M.evaluate(Rt, dev, w)[1]
            pr = per_query(Rt, test, w)
            dR, pR = rnd(base[0], pr[0]); dN, pN = rnd(base[1], pr[1])
            res[name + tag] = {'dev_ndcg': dv, 'R@10': float(np.mean(pr[0])), 'NDCG@10': float(np.mean(pr[1])),
                               'dR': dR, 'pR': pR, 'dN': dN, 'pN': pN, 'w': {k: v for k, v in w.items() if v}}
            print(f'{name + tag:34s}{dv:10.4f}{np.mean(pr[0]):10.4f}{np.mean(pr[1]):10.4f}   ΔR {dR:+.4f} (p={pR:.3f})  ΔNDCG {dN:+.4f} (p={pN:.3f})  w={res[name + tag]["w"]}')
    best = max((k for k in res if '语义网' not in k), key=lambda k: res[k]['dev_ndcg'])
    print(f'\n开发集 NDCG 最高的要件方案：{best}')
    json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'element_variants_results.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
