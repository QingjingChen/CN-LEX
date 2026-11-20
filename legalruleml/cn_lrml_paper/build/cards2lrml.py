#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LEGO ExpertGraph 全量 409 张民法 card → LegalRuleML（civil_cards.lrml），补充 civil_graph.lrml 的 179 条人工规则。

每张 card：
  ConstitutiveStatement（可废止）：if  正条件合取 ∧ Naf(负条件)   then  法律效果合取
      条件、效果是不透明原子（谓词 cne:eg###_pos/neg/eff#，原文见 civil_cards_glossary.json），可检索、可追溯；
      作为规范关系的载体，表达“原则（正条件 → 效果）— 例外（负条件）”。
  结构层 Statements：title / issue_frames / 各字段逐条原文（FactualStatement），无损。
  Association：support edge 指向的《民法典》条文（AKN URI），权重与置信度写在 Comment；authority = #expertgraph。
规范关系（只解析写明了目标的语句，不猜）：
  priority_or_exception 中点名另一张 card 的标题或《民法典》条号 → priority / exception 关系；
      方向候选（“X 优先于 Y”等）只写入旁注 override_candidates_for_review，人工复核后再写成 lrml:OverrideStatement
  distinguish_from 中点名 card 或条号 → distinguish 关系
  negative_conditions 中点名 card 或条号 → exception 关系（例外条件由目标规范提供）
  与 civil_graph 人工规则共享条文的 card → formalisedBy（写入旁注）
用法：../../../.venv/bin/python cards2lrml.py
"""
import collections, json, re, sys
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
LR = HERE.parent.parent
ROOT = LR.parent
OUT = HERE.parent / 'lrml'
DATA = ROOT / 'output/arvix_audit/public_repo_snapshot/data/graph'
sys.path.insert(0, str(LR / 'civil_graph'))
import civil_code as CC      # noqa: E402
import formal_rules as FR    # noqa: E402

L = 'http://docs.oasis-open.org/legalruleml/ns/v1.0/'
R = 'http://ruleml.org/spec'
NSMAP = {'lrml': L, 'ruleml': R, 'xs': 'http://www.w3.org/2001/XMLSchema',
         'xsi': 'http://www.w3.org/2001/XMLSchema-instance', 'lrmlv': L + 'metamodel#'}
AKN = '/akn/cn/act/2020-05-28/civil-code/zho@/!main#art_{}'
ART = re.compile(r'(《[^》]{1,20}》)?第([0-9一二三四五六七八九十百千零]+)条')
PRIO = re.compile(r'优先|特别法|特别规定|另有规定')
EXC = re.compile(r'除外|例外|但书|但是|不适用|排除|不得对抗|不在此限')
FIELDS = [('issue_frames', '争点'), ('positive_conditions', '正条件'), ('negative_conditions', '负条件'),
          ('legal_effects', '法律效果'), ('distinguish_from', '区分'), ('priority_or_exception', '优先与例外')]


def E(parent, tag, text=None, **attr):
    ns, name = tag.split(':')
    e = etree.SubElement(parent, f'{{{NSMAP[ns]}}}{name}', **attr) if parent is not None else etree.Element(f'{{{NSMAP[ns]}}}{name}', nsmap=NSMAP, **attr)
    if text is not None:
        e.text = text
    return e


def atom(parent, pred, args=('P',)):
    a = E(parent, 'ruleml:Atom'); E(a, 'ruleml:Rel', iri=f'cne:{pred}')
    for x in args:
        E(a, 'ruleml:Var', x)


def cn2int(s):
    return int(s) if s.isdigit() else CC.cn2int(s)


def main():
    rows = [json.loads(l) for l in open(DATA / 'nodes.jsonl', encoding='utf-8')]
    cards = []
    seen = collections.Counter()
    for r in rows:
        cards.append((f"eg{len(cards):03d}", r['id'], seen[r['id']], r['card'])); seen[r['id']] += 1
    edges = collections.defaultdict(dict)
    for l in open(DATA / 'edges.jsonl', encoding='utf-8'):
        e = json.loads(l)
        if e['weight'] > edges[e['node']].get(e['article'], (0, ''))[0]:
            edges[e['node']][e['article']] = (e['weight'], e['confidence'])
    arts = CC.articles()
    titles = {}
    for k, cid, _, c in cards:
        titles.setdefault(c['title'], k)
    title_list = sorted((t for t in titles if len(t) >= 3), key=len, reverse=True)
    # 泛化标题（被很多张 card 的语句提到，如“民事法律行为”）不作为关系目标：抽查中这类匹配多为概念提及而非规范关系
    df = collections.Counter()
    for _, _, _, c in cards:
        blob = ' '.join(x for f, _ in FIELDS for x in (c.get(f) or []))
        for tt in title_list:
            if tt in blob:
                df[tt] += 1
    GENERIC = {tt for tt, n in df.items() if n > 15}
    formal_arts = collections.defaultdict(set)
    for _, rs in FR.MODULES.values():
        for r in rs:
            for s in r['srcs']:
                formal_arts[int(re.match(r'art(\d+)', s).group(1))].add(r['key'])

    root = E(None, 'lrml:LegalRuleML')
    root.addprevious(etree.Comment(' 由 cards2lrml.py 从 LEGO ExpertGraph（409 张 card）生成，请勿手改。条件与效果为不透明原子；规范关系见 civil_cards_glossary.json '))
    E(root, 'lrml:Prefix', key='cne', refID='http://example.org/lexgo/expertgraph-vocab#')
    srcs = E(root, 'lrml:LegalSources', key='legal-sources')
    used = sorted({a for _, cid, _, _ in cards for a in edges.get(cid, {}) if 1 <= a <= 1260})
    for a in used:
        s = E(srcs, 'lrml:LegalSource', key=f'cc-art{a}', sameAs=AKN.format(a))
        E(s, 'lrml:Comment', '《民法典》' + arts[a])
    auths = E(root, 'lrml:Authorities', key='authorities')
    E(E(auths, 'lrml:Authority', key='expertgraph'), 'lrml:Comment', 'LEGO ExpertGraph 概念卡（专家知识图谱结构化而成；未逐条经法律专家复核）')
    times = E(root, 'lrml:Times', key='times')
    t = etree.SubElement(times, f'{{{R}}}Time', key=':t-2021-01-01')
    d = etree.SubElement(t, f'{{{R}}}Data'); d.set(f'{{{NSMAP["xsi"]}}}type', 'xs:dateTime'); d.text = '2021-01-01T00:00:00Z'
    tc = E(E(root, 'lrml:TemporalCharacteristics', key='tb-cc'), 'lrml:TemporalCharacteristic')
    E(tc, 'lrml:forStatus', iri='lrmlv:Efficacious'); E(tc, 'lrml:hasStatusDevelopment', iri='lrmlv:Starts'); E(tc, 'lrml:atTime', keyref='#t-2021-01-01')
    assocs = E(root, 'lrml:Associations', key='associations')
    struct = E(root, 'lrml:Statements', key='expertgraph-structure'); E(struct, 'lrml:Comment', 'ExpertGraph 概念卡（结构层，无损）')
    rules = E(root, 'lrml:Statements', key='expertgraph-rules'); E(rules, 'lrml:Comment', 'ExpertGraph 规范层：原则（正条件→效果）与例外（Naf）')

    gloss = {'cards': {}, 'predicates': {}, 'relations': [], 'stats': collections.Counter()}
    overrides = []
    for k, cid, idx, c in cards:
        sup = edges.get(cid, {})
        gloss['cards'][k] = {'id': cid, 'dup': idx, 'title': c['title'], 'articles': sorted(sup),
                             'formalisedBy': sorted({r for a in sup for r in formal_arts.get(a, ())})}
        cs = E(struct, 'lrml:Statements', key=f'{k}-card'); E(cs, 'lrml:Comment', c['title'])
        for f, zh in FIELDS:
            fs = E(cs, 'lrml:Statements', key=f'{k}-{f}'); E(fs, 'lrml:Comment', zh)
            for i, s in enumerate(c.get(f) or []):
                E(E(fs, 'lrml:FactualStatement', key=f'{k}-{f}-{i}'), 'lrml:Comment', s)
                gloss['stats']['structure_items'] += 1
        st = E(rules, 'lrml:ConstitutiveStatement', key=k)
        E(st, 'lrml:Comment', f"{c['title']}（{'；'.join(c.get('issue_frames') or [])}）")
        rule = E(st, 'ruleml:Rule', closure='universal', key=':' + k)
        cond = E(E(rule, 'ruleml:if'), 'ruleml:And')
        pos, neg, eff = c.get('positive_conditions') or [], c.get('negative_conditions') or [], c.get('legal_effects') or []
        for i, s in enumerate(pos):
            p = f'{k}_pos{i}'; gloss['predicates'][p] = s; atom(cond, p)
        for i, s in enumerate(neg):
            p = f'{k}_neg{i}'; gloss['predicates'][p] = s; atom(E(cond, 'ruleml:Naf'), p)
        if not pos and not neg:
            atom(cond, f'{k}_applies')
        then = E(E(rule, 'ruleml:then'), 'ruleml:And')
        for i, s in enumerate(eff or [c['title']]):
            p = f'{k}_eff{i}'; gloss['predicates'][p] = s; atom(then, p)
        a = E(assocs, 'lrml:Association')
        if sup:
            E(a, 'lrml:Comment', '; '.join(f'art{x}: weight={w:.3f} confidence={cf}' for x, (w, cf) in sorted(sup.items())))
        for x in sorted(sup):
            if 1 <= x <= 1260:
                E(a, 'lrml:appliesSource', keyref=f'#cc-art{x}')
        E(a, 'lrml:appliesAuthority', keyref='#expertgraph')
        E(a, 'lrml:appliesTemporalCharacteristics', keyref='#tb-cc')
        E(a, 'lrml:appliesStrength', iri='lrmlv:Defeasible')
        E(a, 'lrml:toTarget', keyref='#' + k)
        gloss['stats']['rules'] += 1
        gloss['stats']['naf_conditions'] += len(neg)
        gloss['stats']['rules_with_naf'] += bool(neg)

        # ---- 规范关系
        for field, kind_default in (('priority_or_exception', None), ('distinguish_from', 'distinguish'), ('negative_conditions', 'exception')):
            for s in c.get(field) or []:
                targets = []
                for m in ART.finditer(s):
                    if m.group(1) and m.group(1) not in ('《民法典》',):
                        continue
                    n = cn2int(m.group(2))
                    if 1 <= n <= 1260 and not re.search(r'(合同法|物权法|侵权责任法|担保法|婚姻法|继承法)[^》]{0,3}$', s[:m.start()]):
                        targets.append(('article', n, m.start()))
                txt = s
                for tt in title_list:
                    if tt != c['title'] and tt in txt and tt not in c['title'] and tt not in GENERIC:
                        targets.append(('card', titles[tt], s.find(tt)))
                        txt = txt.replace(tt, '□' * len(tt))
                if not targets:
                    continue
                kind = kind_default or ('priority' if PRIO.search(s) else 'exception' if EXC.search(s) else 'related')
                for typ, tgt, pos_ in targets:
                    rel = {'from': k, 'to_type': typ, 'to': tgt, 'type': kind, 'field': field, 'text': s}
                    if kind == 'priority' and typ == 'card':
                        m = re.search(r'优先(?:于|适用)', s)
                        if m and pos_ > m.start():
                            rel['override'] = (k, tgt)       # 本规范 优先于 目标
                        elif m and pos_ < m.start():
                            rel['override'] = (tgt, k)       # 目标 优先（适用）
                    if 'override' in rel and rel['override'][0] != rel['override'][1]:
                        overrides.append((*rel['override'], s))
                    gloss['relations'].append(rel)
                    gloss['stats'][f'rel_{kind}_{typ}'] += 1
    # 方向由文字自动判断不可靠（抽查约四成方向错误），因此不自动生成 OverrideStatement：
    # 候选只写入旁注，待人工复核后再写成 Override；文件中的规范关系以无向 priority / exception 链接表示。
    seen_ov = []
    for over, under, s in overrides:
        if (over, under) not in [(o, u) for o, u, _ in seen_ov]:
            seen_ov.append((over, under, s))
    # 由人工核对过的 Override（civil_graph 的 47 条）继承方向：规则 A 优先于 B ⇒ 以 A 的条文为主条文的 card 优先于以 B 的条文为主条文的 card
    RA = {r['key']: {int(re.match(r'art(\d+)', x).group(1)) for x in r['srcs']} for _, rs in FR.MODULES.values() for r in rs}
    home = {k: [a for a, _ in sorted(edges.get(cid, {}).items(), key=lambda x: -x[1][0])[:2]] for k, cid, _, _ in cards}
    derived = []
    for over, under, why in FR.OVERRIDES:
        if RA[over] & RA[under]:          # 两条规则出自同一条文时，card 与规则的对应不唯一，不继承
            continue
        A = [k for k in home if home[k][:1] and home[k][0] in RA[over]]      # 只用 card 的首要条文
        B = [k for k in home if home[k][:1] and home[k][0] in RA[under]]
        for x in A:
            for y in B:
                if x != y and (x, y) not in [(d[0], d[1]) for d in derived] and (y, x) not in [(d[0], d[1]) for d in derived]:
                    derived.append((x, y, over, under, why))
    # 抽查约一半正确（card 的首要条文常是上位概念的锚点），因此同样只写入待复核清单，不写成 OverrideStatement。
    gloss['derived_overrides'] = [{'over': x, 'under': y, 'from_rule_override': [o, u], 'why': w} for x, y, o, u, w in derived]
    gloss['stats']['inherited_override_candidates_for_review'] = len(derived)
    gloss['override_candidates_for_review'] = [{'over': o, 'under': u, 'text': s} for o, u, s in seen_ov]
    gloss['stats']['override_candidates_for_review'] = len(seen_ov)
    gloss['stats']['generic_titles_excluded'] = len(GENERIC)
    gloss['stats']['legal_sources'] = len(used)
    gloss['stats']['cards_with_formal_rules'] = sum(bool(v['formalisedBy']) for v in gloss['cards'].values())

    OUT.mkdir(exist_ok=True)
    path = OUT / 'civil_cards.lrml'
    etree.ElementTree(root).write(str(path), xml_declaration=True, encoding='UTF-8', pretty_print=True)
    schema = etree.XMLSchema(etree.parse(str(LR / 'civil_graph/schema/lrml-compact.xsd')))
    ok = schema.validate(etree.parse(str(path)))
    gloss['stats'] = dict(gloss['stats']); gloss['stats']['xsd_valid'] = ok
    json.dump(gloss, open(OUT / 'civil_cards_glossary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(gloss['stats'], ensure_ascii=False, indent=1))
    if not ok:
        print('\n'.join(str(e) for e in list(schema.error_log)[:5]))


if __name__ == '__main__':
    main()
