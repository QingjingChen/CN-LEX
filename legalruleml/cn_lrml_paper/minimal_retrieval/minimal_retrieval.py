#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小可运行版：民法法条检索 + CLeXML 语义网（有类型、有方向的规范关系）。只依赖 numpy 和 Python 标准库。

复现论文表 2 的三行：Dense、+ elements、+ new graph（typed + directed）。
    python minimal_retrieval.py                 # 跑完整实验，打印测试集指标
    python minimal_retrieval.py --explain 296   # 逐步展示某一题：检索、语义网推送、重排、NDCG 怎么算

流程（每一步在下面都有对应函数）：
  1 读数据      题目（含金标条文、dev/test 划分）、1,260 条法条、预先算好的 BGE-m3 向量
  2 读语义网    直接解析 civil_review.lrml：规则 → 条文（LegalSource / Association），
                Override（有方向）、依赖 / 例外候选、明文引致 → 条文之间“有类型、有方向”的边
  3 第一阶段    Dense：查询向量 · 条文向量 = 余弦相似度，取前 20 条为候选、前 5 条为“种子”
  4 第二阶段    重排同一批 20 个候选：
                S(a) = 归一化 dense(a) + w_e · 归一化要件相似度(a) + Σ_t w_t · N_t(a)
                N_t(a) = Σ_{种子 b，且语义网中有 b →t a 的边} 归一化 dense(b)，再在候选内 min-max 归一化
  5 选权重      只在 76 道开发题上，按 NDCG@10 逐个关系类型选 w（坐标上升，2 轮）
  6 评测        176 道测试题：Recall@10、NDCG@10
"""
import argparse, collections, json, math, os, re
import xml.etree.ElementTree as ET
import numpy as np

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
GRID = (0, .05, .1, .2, .3)
TYPES = ('override_up', 'override_down', 'depends', 'exception', 'textref')
L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'


# ---------------------------------------------------------------- 1 读数据
def load():
    Q = [json.loads(l) for l in open(f'{D}/queries.jsonl', encoding='utf-8')]
    A = [json.loads(l) for l in open(f'{D}/articles.jsonl', encoding='utf-8')]
    XQ, XA, XE = (np.load(f'{D}/emb_{n}.npy') for n in ('queries', 'articles', 'elements'))
    has = np.load(f'{D}/has_element.npy')
    return Q, A, XQ, XA, XE, has


# ---------------------------------------------------------------- 2 读语义网（CLeXML LegalRuleML）
def read_graph(path, valid):
    """返回 {关系类型: {条文 b: {条文 a, ...}}}，含义：检索到条文 b 时，应当去看条文 a。"""
    root = ET.parse(path).getroot()
    # 2a 法源：LegalSource 的 sameAs 是 Akoma Ntoso URI，例如 .../civil-code/zho@/!main#art_1199
    src = {}
    for e in root.iter(L + 'LegalSource'):
        m = re.search(r'#art_(\d+(?:_\d+)?)(?:__para_\d+)?$', e.get('sameAs', ''))
        if m:
            src[e.get('key')] = m.group(1).replace('_', '-')
    # 2b 规则 → 条文：Association 把 appliesSource（法源）绑定到 toTarget（规则）
    rule_arts = collections.defaultdict(set)
    for e in root.iter(L + 'Association'):
        arts = {src[s.get('keyref', '').lstrip('#')] for s in e.findall(L + 'appliesSource') if s.get('keyref', '').lstrip('#') in src}
        for t in e.findall(L + 'toTarget'):
            rule_arts[t.get('keyref').lstrip('#')] |= arts
    G = collections.defaultdict(lambda: collections.defaultdict(set))

    def add(t, A, B):
        for a in A:
            for b in B:
                if a != b and a in valid and b in valid:
                    G[t][a].add(b)
    # 2c 第一层：标准 Override(over, under)。两个方向分开：
    #     override_up   检索到被覆盖的一般规则 → 去看优先的特别规则
    #     override_down 检索到特别规则 → 去看它所排除的一般规则
    for o in root.iter(L + 'Override'):
        over, under = o.get('over').lstrip('#'), o.get('under').lstrip('#')
        add('override_up', rule_arts[under], rule_arts[over])
        add('override_down', rule_arts[over], rule_arts[under])
    # 2d 第二层候选（写在 FactualStatement 的 Comment 里，前缀 CNLR_REVIEW_META:）
    #     depends   规则 r 的条件谓词由规则 r' 推出 → 检索到 r 时去看 r'
    #     exception 规则 r 的“除非”（Naf）谓词由 r' 推出 → 检索到 r 时去看 r'
    #     textref   条文明文写“依照本法第 X 条” → 去看第 X 条
    for e in root.iter(L + 'FactualStatement'):
        c = e.find(L + 'Comment')
        if c is None or not c.text or 'CNLR_REVIEW_META:' not in c.text:
            continue
        meta = json.loads(c.text.split('CNLR_REVIEW_META:', 1)[1])
        r = meta['record']
        if meta['kind'] == 'relation_group':
            t = {'depends_candidate': 'depends', 'exception_candidate': 'exception',
                 'negative_condition_candidate': 'exception'}.get(r['type'])
            if t:
                for _, target in r['targets']:
                    add(t, rule_arts[r['from_rule']], rule_arts[target])
        elif meta['kind'] == 'text_references':
            add('textref', r.get('from_articles', []), r.get('to_articles', []))
    return {t: G[t] for t in TYPES}


# ---------------------------------------------------------------- 工具
def minmax(v):
    lo, hi = min(v.values()), max(v.values())
    return {k: (x - lo) / ((hi - lo) or 1.0) for k, x in v.items()}


def ndcg_at_k(ranked, gold, k=10, show=False):
    """二值相关：金标条文 gain = 1，其他 0。
       DCG@k  = Σ_{i=1..k} rel_i / log2(i + 1)
       IDCG@k = 把 min(|G|, k) 个金标都排在最前面时的 DCG
       NDCG@k = DCG@k / IDCG@k"""
    dcg, lines = 0.0, []
    for i, a in enumerate(ranked[:k], start=1):
        rel = 1 if a in gold else 0
        dcg += rel / math.log2(i + 1)
        if show:
            lines.append(f'      第{i:2d}名 第{a:>4s}条  rel={rel}  rel/log2({i}+1) = {rel / math.log2(i + 1):.4f}')
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    if show:
        print('\n'.join(lines))
        print(f'      DCG@{k} = {dcg:.4f}')
        print(f'      IDCG@{k} = ' + ' + '.join(f'1/log2({i}+1)' for i in range(1, min(len(gold), k) + 1)) + f' = {idcg:.4f}'
              f'   （{len(gold)} 个金标都排在最前面时的 DCG）')
        print(f'      NDCG@{k} = {dcg:.4f} / {idcg:.4f} = {dcg / idcg:.4f}')
    return dcg / idcg


def recall_at_k(ranked, gold, k=10):
    return len(set(ranked[:k]) & gold) / len(gold)


# ---------------------------------------------------------------- 3–4 两阶段检索
class Retriever:
    def __init__(self, Q, A, XQ, XA, XE, has, G):
        self.ids = [a['id'] for a in A]
        self.G = G
        self.feat = {}
        for i, q in enumerate(Q):
            x = XQ[i]
            dense = dict(zip(self.ids, map(float, XA @ x)))          # 3 第一阶段：余弦相似度（向量已归一化，点积即余弦）
            order = sorted(dense, key=lambda a: -dense[a])
            cands, seeds = order[:20], order[:5]
            d = minmax({a: dense[a] for a in cands})                  # 候选内归一化到 [0, 1]
            el_raw = {a: (float(XE[j] @ x) if has[j] else None) for j, a in enumerate(self.ids) if a in set(cands)}
            lo = min(v for v in el_raw.values() if v is not None)
            el = minmax({a: (v if v is not None else lo) for a, v in el_raw.items()})
            norm = {}
            for t, adj in G.items():                                  # 4 语义网推送：只沿边的方向，从种子推给候选
                v = {a: sum(d[b] for b in seeds if b != a and a in adj.get(b, ())) for a in cands}
                norm[t] = minmax(v) if len(set(v.values())) > 1 else {a: 0.0 for a in cands}
            self.feat[q['qid']] = dict(dense=dense, order=order, cands=cands, seeds=seeds, d=d, el=el, norm=norm)

    def rank(self, qid, w):
        f = self.feat[qid]
        s = {a: f['d'][a] + w.get('elem', 0) * f['el'][a] + sum(w.get(t, 0) * f['norm'][t][a] for t in f['norm']) for a in f['cands']}
        top = sorted(s, key=lambda a: -s[a])
        return top + [a for a in f['order'] if a not in s], s       # 候选之外的条文保持 Dense 顺序，排在后面


def evaluate(R, qs, w):
    rs = [R.rank(q['qid'], w)[0] for q in qs]
    return (float(np.mean([recall_at_k(r, set(q['gold'])) for r, q in zip(rs, qs)])),
            float(np.mean([ndcg_at_k(r, set(q['gold'])) for r, q in zip(rs, qs)])))


def tune(R, dev, types):
    """5 选权重：先选要件权重 w_e，再对每个关系类型轮流选（2 轮）；并列时取更小的权重。"""
    w = {'elem': max(GRID, key=lambda x: (evaluate(R, dev, {'elem': x})[1], -x))}
    for t in types:
        w[t] = 0
    for _ in range(2):
        for t in types:
            w[t] = max(GRID, key=lambda x: (evaluate(R, dev, dict(w, **{t: x}))[1], -x))
    return w


# ---------------------------------------------------------------- 示例讲解
def explain(R, Q, A, w, qid):
    q = next(x for x in Q if x['qid'] == qid); gold = set(q['gold']); f = R.feat[qid]
    name = {a['id']: a['text'][:28].replace('\n', ' ') for a in A}
    print(f'\n================ 第 {qid} 题（{q["split"]}）================')
    print('查询（题干 + 问题 + 选项）：', q['text'][:160].replace('\n', ' '), '…')
    print('金标条文（解析中引用的《民法典》条文）：', '、'.join(f'第{g}条' for g in sorted(gold, key=int)))
    print('\n【第一阶段 Dense】余弦相似度最高的 10 条：')
    for i, a in enumerate(f['order'][:10], 1):
        print(f'  {i:2d}. 第{a:>4s}条  cos={f["dense"][a]:.4f}  {"★金标" if a in gold else "    "}  {name[a]}')
    print('\n  Dense 的 NDCG@10：'); ndcg_at_k(f['order'], gold, show=True)
    print('\n【第二阶段】种子 = Dense 前 5 名：' + '、'.join(f'第{b}条' for b in f['seeds']))
    print('  语义网把证据从种子沿关系方向推给候选（只列出有推送的候选）：')
    for t in TYPES:
        if not w.get(t):
            continue
        for a in f['cands']:
            src = [b for b in f['seeds'] if b != a and a in R.G[t].get(b, ())]
            if src:
                print(f'    {t:13s} 第{a:>4s}条 ← ' + '、'.join(f'第{b}条(ŝ={f["d"][b]:.2f})' for b in src)
                      + f'  → 归一化后 N={f["norm"][t][a]:.2f}，乘权重 {w[t]} 得 +{w[t] * f["norm"][t][a]:.3f}')
    full, s = R.rank(qid, w)
    print(f'\n  重排公式 S = ŝ_dense + {w["elem"]}·ŝ_要件 + Σ w_t·N_t ，重排后前 10：')
    for i, a in enumerate(full[:10], 1):
        extra = sum(w.get(t, 0) * f['norm'][t][a] for t in TYPES)
        print(f'  {i:2d}. 第{a:>4s}条  S={s[a]:.3f} = {f["d"][a]:.3f} + {w["elem"] * f["el"][a]:.3f} + {extra:.3f}'
              f'  {"★金标" if a in gold else ""}  (Dense 第{f["order"].index(a) + 1}名)')
    print('\n  重排后的 NDCG@10：'); ndcg_at_k(full, gold, show=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--explain', type=int)
    a = ap.parse_args()
    Q, A, XQ, XA, XE, has = load()
    G = read_graph(f'{D}/civil_review.lrml', {x['id'] for x in A})
    print('语义网中的条文边数：', {t: sum(map(len, adj.values())) for t, adj in G.items()})
    R = Retriever(Q, A, XQ, XA, XE, has, G)
    dev = [q for q in Q if q['split'] == 'dev']; test = [q for q in Q if q['split'] == 'test']
    w_e = tune(R, dev, [])
    w_g = tune(R, dev, list(TYPES))
    print(f'开发集 {len(dev)} 题选出的权重：+elements {w_e}；+new graph {w_g}')
    print(f'\n测试集 {len(test)} 题：              Recall@10  NDCG@10')
    for name, w in (('Dense', {}), ('Dense + elements', w_e), ('+ new graph (typed + directed)', w_g)):
        r, n = evaluate(R, test, w)
        print(f'  {name:32s} {r:.4f}    {n:.4f}')
    if a.explain is not None:
        explain(R, Q, A, w_g, a.explain)
    else:   # 自动挑一道语义网让 NDCG 提升最多的测试题作示例
        gains = [(ndcg_at_k(R.rank(q['qid'], w_g)[0], set(q['gold'])) - ndcg_at_k(R.rank(q['qid'], w_e)[0], set(q['gold'])), q['qid']) for q in test]
        best = max(gains)[1]
        print(f'\n（示例：语义网让 NDCG@10 提升最多的测试题是第 {best} 题；用 --explain {best} 查看逐步过程）')


if __name__ == '__main__':
    main()
