#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 B（全量）：民法法条检索，语义层 = 人工规则层（179 条）+ ExpertGraph 全量 card 规则（409 条，civil_cards.lrml）。

文档视图（都不加 AKN 路径；诊断见 civil_diagnose.py）：
  text            条文原文
  text+rule       + 人工规则层的规范 / 条件 / 效果 / 例外（覆盖 91 条）
  text+card       + 该条 support 权重最高的 card 的 标题 / 条件 / 例外 / 效果（覆盖 1,211 条）
  text+rule+card  两者都加
关系扩展的边：
  formal   人工规则层 override / exception / depends（与之前相同）
  card     civil_cards_glossary.json 中 exception / priority / related 链接：card 的主条文（support 前 2）↔ 目标条文 / 目标 card 的主条文
视图与 γ 都在开发集（30%，seed 0，与 civil_run.py 相同划分）上选择；测试集只报告。
用法：~/.venvs/lcr_jurex/bin/python civil_full_run.py
"""
import collections, json, os, random
from retrieval_lib import embed, minmax, metrics, mean, randomization, HERE
import civil_run as CR

ARTS, Q = CR.ARTS, CR.Q
G = json.load(open(os.path.join(HERE, '../lrml/civil_cards_glossary.json'), encoding='utf-8'))
CARDS = json.load(open(os.path.join(HERE, '../../../output/arvix_audit/public_repo_snapshot/data/graph/nodes.jsonl'.replace('nodes.jsonl', 'nodes.jsonl')), encoding='utf-8')) if False else None
rows = [json.loads(l) for l in open(os.path.join(HERE, '../../../output/arvix_audit/public_repo_snapshot/data/graph/nodes.jsonl'), encoding='utf-8')]
W = collections.defaultdict(dict)
for l in open(os.path.join(HERE, '../../../output/arvix_audit/public_repo_snapshot/data/graph/edges.jsonl'), encoding='utf-8'):
    e = json.loads(l)
    W[e['node']][e['article']] = max(W[e['node']].get(e['article'], 0), e['weight'])
card_text, home = {}, {}
for i, r in enumerate(rows):
    k = f'eg{i:03d}'; c = r['card']
    s = f"规范：{c['title']}。条件：{'；'.join(c.get('positive_conditions') or [])}。"
    if c.get('negative_conditions'):
        s += f"例外：{'；'.join(c['negative_conditions'])}。"
    s += f"效果：{'；'.join(c.get('legal_effects') or [])}。"
    card_text[k] = s
    home[k] = [a for a, _ in sorted(W[r['id']].items(), key=lambda x: -x[1])[:2]]
best_card = {}
for i, r in enumerate(rows):
    for a, w in W[r['id']].items():
        if w > best_card.get(a, (0, None))[0]:
            best_card[a] = (w, f'eg{i:03d}')


def view(name):
    out = {}
    for a, v in ARTS.items():
        t = v['text']
        if 'rule' in name and '规范：' in v['lrml']:
            t += '\n' + ''.join(x for x in v['lrml'].split('\n') if x.startswith('规范：'))
        if 'card' in name and int(a) in best_card:
            t += '\n' + card_text[best_card[int(a)][1]]
        out[a] = t
    return out


def dense(name):
    ids, A = embed(view(name), max_len=1024, bs=16)
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    S = X @ A.T
    return {str(q['qid']): {ids[j]: float(S[i, j]) for j in range(len(ids))} for i, q in enumerate(Q)}


def card_edges():
    E = collections.defaultdict(dict)
    def add(a, b):
        a, b = str(a), str(b)
        if a != b:
            E[a][b] = E[a].get(b, 0) + 1; E[b][a] = E[b].get(a, 0) + 1
    for r in G['relations']:
        if r['type'] == 'distinguish':
            continue
        tgt = [r['to']] if r['to_type'] == 'article' else home.get(r['to'], [])
        for a in home.get(r['from'], []):
            for b in tgt:
                add(a, b)
    return E


def merge(*Ns):
    out = collections.defaultdict(dict)
    for N in Ns:
        for a, nb in N.items():
            for b, w in nb.items():
                out[a][b] = out[a].get(b, 0) + w
    return out


def ev(run, qs):
    return {str(q['qid']): metrics(run[str(q['qid'])], {str(a): 1 for a in q['gold']}, ks_r=(5, 10), ks_n=(10,)) for q in qs}


def main():
    rng = random.Random(0)
    qs = sorted(Q, key=lambda q: q['qid'])
    dev = set(q['qid'] for q in rng.sample(qs, round(.3 * len(qs))))
    DEV = [q for q in qs if q['qid'] in dev]; TEST = [q for q in qs if q['qid'] not in dev]
    covered_card = sum(any(g in best_card for g in q['gold']) for q in TEST)
    print(f'test {len(TEST)}; gold articles with a card: {sum(g in best_card for q in TEST for g in q["gold"])}/{sum(len(q["gold"]) for q in TEST)}'
          f'; questions with ≥1 carded gold: {covered_card}')
    views = {v: dense(v) for v in ('text', 'text+rule', 'text+card', 'text+rule+card')}
    best_view = max(views, key=lambda v: mean(ev(views[v], DEV))['R@10'])
    NF = CR.neighbours(['override', 'exception', 'depends'])
    NC = card_edges()
    NALL = merge(NF, NC)
    print('card-derived article edges:', sum(map(len, NC.values())) // 2, '| merged:', sum(map(len, NALL.values())) // 2)
    runs, gam = {}, {}
    for v in views:
        runs[f'Dense({v})'] = views[v]
    for base in ('text', best_view):
        for en, N in (('formal', NF), ('card', NC), ('formal+card', NALL)):
            g = max(CR.GAMMAS, key=lambda g: (mean(ev(CR.expand(views[base], N, g), DEV))['NDCG@10'], -g))
            gam[f'{base}|{en}'] = g
            runs[f'Dense({base})+{en}-rel'] = CR.expand(views[base], N, g)
    per = {n: ev(r, TEST) for n, r in runs.items()}
    cov = {str(q['qid']) for q in TEST if q['covered']}
    res = {'best_view_on_dev': best_view, 'gamma_on_dev': gam, 'test': {n: mean(p) for n, p in per.items()},
           'test_rulecovered': {n: mean({k: p[k] for k in cov}) for n, p in per.items()},
           'dev': {v: mean(ev(views[v], DEV)) for v in views}, 'sig': {}}
    for n in runs:
        if n != 'Dense(text)':
            res['sig'][n] = {m: randomization(per['Dense(text)'], per[n], m) for m in ('R@10', 'NDCG@10', 'MRR')}
    json.dump(res, open(os.path.join(HERE, 'results/civil_full_results.json'), 'w'), ensure_ascii=False, indent=1)
    print('view chosen on dev:', best_view, '| gamma:', gam)
    print('dev R@10:', {v: round(m['R@10'], 4) for v, m in res['dev'].items()})
    keys = ['R@5', 'R@10', 'NDCG@10', 'MRR']
    print(f"{'method':38s}" + ''.join(f'{k:>9s}' for k in keys) + '  | rule-covered R@10 NDCG@10')
    for n in runs:
        m, c = res['test'][n], res['test_rulecovered'][n]
        print(f'{n:38s}' + ''.join(f'{m[k]:9.4f}' for k in keys) + f"  |  {c['R@10']:.4f} {c['NDCG@10']:.4f}")
    for n, s in res['sig'].items():
        print(f'  {n:38s}', '  '.join(f'Δ{m}={d:+.4f} p={p:.3f}' for m, (d, p) in s.items()))


if __name__ == '__main__':
    main()
