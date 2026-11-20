#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民法法条检索实验的数据准备（LEGO / LexGo 题目，《民法典》1260 条）。

输出 data/civil_data.json：
  articles : {n: {text, akn, lrml}}       三种文档视图
      text = 条文原文
      akn  = Akoma Ntoso 层级路径（编/分编/章/节）+ 原文
      lrml = akn + LegalRuleML 语义层（规则层 Comment、条件/效果谓词中文释义、结构层概念名）
  edges    : {type: [[a, b, w], ...]}      条文级关系，均由 LegalRuleML 导出
      override   Override(over, under) 两侧条文
      exception  规则 r 含 Naf q，q 由规则 r' 推出 → art(r) — art(r')
      depends    规则 r 的条件谓词 p 由规则 r' 推出 → art(r) — art(r')
      cocite     结构层同一上位节点下被引用的两条（同主题；权威 = graph，弱关系）
  queries  : [{qid, text, gold:[n], lego:[n]}]
金标 = 解析中明确引用的《民法典》条文（graph_parse.cites_of，law == civil-code 且非推断），旧法（合同法等）引文不计。
用法：../../.venv/bin/python civil_prep.py
"""
import collections, glob, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LRML = HERE.parent.parent
ROOT = LRML.parent
sys.path.insert(0, str(LRML / 'civil_graph'))
import civil_code as CC            # noqa: E402
import formal_rules as FR          # noqa: E402
from graph_parse import cites_of, EXAM  # noqa: E402
import pandas as pd                # noqa: E402

art_of = lambda s: int(re.match(r'art(\d+)', s).group(1))


def hierarchy():
    """逐行扫描原文，记录每条所在的 编 / 分编 / 章 / 节。"""
    path, out = {}, {}
    lv = {'编': 0, '分编': 1, '章': 2, '节': 3}
    for line in CC.CODE.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        m = re.match(r'^第[一二三四五六七八九十]+(分编|编|章|节)\s*(.*)$', s)
        if m and len(s) < 40:
            k = m.group(1)
            path[k] = s.replace('　', ' ')
            for kk, l in lv.items():
                if l > lv[k]:
                    path.pop(kk, None)
            continue
        m = re.match(r'^第([一二三四五六七八九十百千零]+)条　', s)
        if m:
            n = CC.cn2int(m.group(1))
            out.setdefault(n, ' / '.join(path[k] for k in sorted(path, key=lv.get)))
    return out


def preds(lits):
    for l in lits:
        for a in (l[1] if isinstance(l, tuple) else [l]):
            for x in a.split(' '):
                m = re.match(r'([-~]?)(\w+)\(', x)
                if m:
                    yield m.group(1) == '~', m.group(2)


def heads(r):
    hs = r['heads'] if isinstance(r['heads'], list) else [r['heads']]
    out = set()
    for h in hs:
        h = h if isinstance(h, str) else h[-1]
        m = re.match(r'-?(\w+)', h)
        out.add(m.group(1))
    return out


def main():
    arts = CC.articles()
    hier = hierarchy()
    rules = [r for _, rs in FR.MODULES.values() for r in rs]
    RA = {r['key']: {art_of(s) for s in r['srcs']} for r in rules}
    covered = set().union(*RA.values())
    zh = lambda p: FR.ZH.get(p, p)

    # ---- 语义层文本
    sem = collections.defaultdict(list)
    for r in rules:
        conds = [zh(p) for neg, p in preds(r['body']) if not neg]
        excs = [zh(p) for neg, p in preds(r['body']) if neg]
        eff = [zh(p) for p in heads(r)]
        s = f"规范：{r['note']}。条件：{'、'.join(conds)}。效果：{'、'.join(eff)}。"
        if excs:
            s += f"例外：{'、'.join(excs)}。"
        for a in RA[r['key']]:
            sem[a].append(s)
    nodes = json.load(open(LRML / 'civil_graph' / 'graph_nodes.json', encoding='utf-8'))
    N = {n['id']: n for n in nodes}
    def title(n):
        t = n.get('concept') or n.get('classifier') or n['clean']
        return EXAM.sub('', re.sub(r'^[（(]?[一二三四五六七八九十\d①-⑳]+[)）、.．]?', '', t)).strip()[:30]
    concepts = collections.defaultdict(collections.Counter)
    topic = collections.defaultdict(set)
    for n in nodes:
        cs = sorted({c['art'] for c in n['cites'] if c['law'] == 'civil-code' and 1 <= c['art'] <= 1260})
        if not cs:
            continue
        chain, p = [], n
        while p and len(chain) < 4:          # 节点本身 + 至多 3 层上位节点
            chain.append(title(p))
            p = N.get(p['parent'])
        for a in cs:
            for c in chain:
                if c:
                    concepts[a][c] += 1
        anc = N.get(n['parent'])             # 同一上位节点下引用的条文 = 同一主题
        if anc:
            topic[anc['id']].update(cs)
    cocite = collections.Counter()
    for cs in topic.values():
        cs = sorted(cs)
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                cocite[(cs[i], cs[j])] += 1
    docs = {}
    for n, t in arts.items():
        akn = f"{hier.get(n, '')}\n{t}"
        extra = sem.get(n, [])
        cn = [c for c, _ in concepts[n].most_common(15) if c]
        lr = akn + ('\n' + ''.join(extra) if extra else '') + ('\n概念：' + '、'.join(cn) if cn else '')
        docs[n] = {'text': t, 'akn': akn, 'lrml': lr}

    # ---- 条文级关系
    prod = collections.defaultdict(set)
    for r in rules:
        for p in heads(r):
            prod[p].add(r['key'])
    E = collections.defaultdict(collections.Counter)
    def link(t, A, B, w=1):
        for a in A:
            for b in B:
                if a != b:
                    E[t][tuple(sorted((a, b)))] += w
    for o, u, _ in FR.OVERRIDES:
        link('override', RA[o], RA[u])
    for r in rules:
        for neg, p in preds(r['body']):
            for k in prod.get(p, ()):
                link('exception' if neg else 'depends', RA[r['key']], RA[k])
    for (a, b), c in cocite.items():
        E['cocite'][(a, b)] = c
    edges = {t: [[a, b, w] for (a, b), w in c.items()] for t, c in E.items()}

    # ---- 题目
    df = pd.read_excel(glob.glob(str(ROOT / '整体benchmark700道*分配.xlsx'))[0])
    lego = {}
    for l in open(ROOT / 'pfc_v3_40p5_repro/reference_outputs/pfc_v3_aligned.jsonl', encoding='utf-8'):
        r = json.loads(l)
        lego[int(r['qid'])] = r['provided_article_nos']
    pick = lambda row, a, b: str(row[a]) if isinstance(row[a], str) and row[a].strip() else str(row[b])
    qs = []
    for i, row in df.iterrows():
        gold = sorted({c['art'] for c in cites_of(str(row['解析'])) if c['law'] == 'civil-code' and not c['inferred'] and 1 <= c['art'] <= 1260})
        if not gold:
            continue
        text = '\n'.join([pick(row, '案情_改编', '案情事实'), pick(row, '问题_改编', '问题'), pick(row, '问题选项_改编', '问题选项')])
        text = text.replace('**', '').replace('<', '').replace('>', '')
        qs.append({'qid': int(i), 'text': text, 'gold': gold, 'lego': lego.get(int(i), []),
                   'covered': bool(set(gold) & covered)})
    out = {'articles': docs, 'edges': edges, 'queries': qs, 'covered': sorted(covered)}
    (HERE / 'data').mkdir(exist_ok=True)
    json.dump(out, open(HERE / 'data' / 'civil_data.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('articles', len(docs), '| with rule-layer text', len(sem), '| with concepts', sum(1 for a in concepts if concepts[a]))
    print('edges', {t: len(v) for t, v in edges.items()})
    print('queries', len(qs), '/', len(df), '| covered', sum(q['covered'] for q in qs),
          '| mean gold', round(sum(len(q['gold']) for q in qs) / len(qs), 2))


if __name__ == '__main__':
    main()
