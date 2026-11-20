#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 crim_jurex.lrml 的每个罪名自动生成场景，用 DDL 引擎（clingo）检验规则层的逻辑结构：
  T1 完整：四要件的基础事实齐备 → constitutes(p,x,c) 成立
  T2 必要性：分别去掉某一要件的基础事实 → constitutes 不成立（每个罪名 4 个）
  T3 例外：完整事实 + 一项出罪情形 → constitutes 不成立（有例外的罪名）
  T4 转化：完整事实 + 转化条件 → constitutes(p,x,目标罪名) 成立（有转化的罪名）
基础事实 = 不出现在任何规则结论中的谓词；析取取第一支。场景完全由 LegalRuleML 生成，不看罪名文本。
用法：<带 clingo 的 python> test_jurex_rules.py <crim_jurex.lp>
"""
import collections, json, sys
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
LR = HERE.parent.parent
sys.path.insert(0, str(LR / 'civil_graph'))
import run_cases as RC  # noqa: E402

L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
R = '{http://ruleml.org/spec}'
BIND = {'P': 'p', 'X': 'x'}


def lit(atom):
    rel = atom.find(R + 'Rel').get('iri').split(':', 1)[1]
    args = [BIND.get(a.text, a.text.lower()) if a.tag == R + 'Var' else a.text for a in atom if a.tag in (R + 'Var', R + 'Ind')]
    return f'{rel}({",".join(args)})'


def first_branch(f):
    """返回 (正文字列表, Naf 文字列表)；Or 取第一支。"""
    tag = f.tag
    if tag == R + 'Atom':
        return [lit(f)], []
    if tag == R + 'Naf':
        return [], [lit(f.find(R + 'Atom'))] if f.find(R + 'Atom') is not None else []
    kids = [c for c in f if c.tag in (R + 'Atom', R + 'And', R + 'Or', R + 'Naf')]
    if tag == R + 'Or':
        kids = kids[:1]
    pos, neg = [], []
    for c in kids:
        p, n = first_branch(c)
        pos += p; neg += n
    return pos, neg


def main(lp):
    root = etree.parse(str(HERE.parent / 'lrml' / 'crim_jurex.lrml')).getroot()
    rules, heads = {}, collections.defaultdict(list)
    for st in root.iter(L + 'ConstitutiveStatement'):
        rule = st.find(R + 'Rule')
        f = [c for c in rule.find(R + 'if')][0]
        h = [lit(a) for a in rule.find(R + 'then').iter(R + 'Atom')]
        rules[st.get('key')] = (f, h)
        for x in h:
            heads[x.split('(')[0]].append(st.get('key'))
    gloss = json.load(open(HERE.parent / 'lrml' / 'crim_jurex_glossary.json', encoding='utf-8'))

    def base_facts(key, seen=None):
        """把某规则体展开到基础事实（递归到定义该谓词的规则，取第一支）。"""
        seen = seen or set()
        f, _ = rules[key]
        pos, _ = first_branch(f)
        out = []
        for a in pos:
            p = a.split('(')[0]
            defs = [k for k in heads.get(p, []) if k not in seen and '-r-conv-' not in k and k.endswith(('-sub', '-sa', '-obj', '-oa')) or
                    (k not in seen and '-r-enum-' in k and p in [x.split('(')[0] for x in rules[k][1]])]
            if p in ('constitutes',) or not defs:
                out.append(a)
            else:
                out += base_facts(defs[0], seen | {key})
        return out

    res = collections.Counter(); fails = []
    for cid, info in gloss['charges'].items():
        main_key = f'jx-{cid}-r-main'
        if main_key not in rules:
            continue
        goal = f'constitutes(p,x,{cid})'
        el = {code: base_facts(f'jx-{cid}-r-{code}') for code in ('obj', 'oa', 'sub', 'sa')}
        full = [a for v in el.values() for a in v]
        model, _ = RC.solve(full, lp)
        ok = RC.holds(model, goal)[0]
        res['T1_total'] += 1; res['T1_pass'] += ok
        if not ok:
            fails.append((cid, info['name'], 'T1', full))
        for code, facts in el.items():
            rest = [a for a in full if a not in facts]
            model, _ = RC.solve(rest, lp)
            ok = not RC.holds(model, goal)[0]
            res['T2_total'] += 1; res['T2_pass'] += ok
            if not ok:
                fails.append((cid, info['name'], 'T2-' + code, rest))
        _, nafs = first_branch(rules[main_key][0])
        for e in nafs[:2]:
            model, _ = RC.solve(full + [e], lp)
            ok = not RC.holds(model, goal)[0]
            res['T3_total'] += 1; res['T3_pass'] += ok
            if not ok:
                fails.append((cid, info['name'], 'T3', e))
        for key, (f, h) in rules.items():
            if key.startswith(f'jx-{cid}-r-conv-'):
                pos, _ = first_branch(f)
                cond = [a for a in pos if not a.startswith('constitutes(')]
                model, _ = RC.solve(full + cond, lp)
                ok = RC.holds(model, h[0])[0]
                res['T4_total'] += 1; res['T4_pass'] += ok
                if not ok:
                    fails.append((cid, info['name'], 'T4', h[0]))
    out = {'results': dict(res), 'fails': fails[:20]}
    json.dump(out, open(HERE.parent / 'lrml' / 'crim_jurex_tests.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(dict(res), indent=1)); print('fails:', len(fails)); [print(x) for x in fails[:8]]


if __name__ == '__main__':
    main(sys.argv[1])
