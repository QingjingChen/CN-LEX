#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JUREX-4E 专家四要件 → LegalRuleML（crim_jurex.lrml），补充 crim_graph.lrml。

两层，与 crim_graph 相同的组织方式：
  结构层（无损）：每个罪名一个 lrml:Statements，下分 犯罪客体 / 客观方面 / 犯罪主体 / 主观方面 四个标签，
                 专家标注树的每个节点 → Statements（有子节点）或 FactualStatement（叶子），原文在 Comment。
  规则层（规则抽取，不调用 LLM，可复核）：
    constitutes(P,X,c) ⇐ object_c(X) ∧ objective_c(P,X) ∧ subject_c(P) ∧ subjective_c(P,X) ∧ ¬exception_c,k(P,X)
    subject_c(P)     ⇐ generalSubject / specialSubject(P,类型) / minAge(P,n)；写明“单位”可构成时与 unitSubject(P) 析取
    subjective_c     ⇐ mens(P,X,directIntent|intent|negligence) ∧ knowledge(P,X) ∧ purpose(P,X,目的)
    objective_c      ⇐ conduct_c(P,X) ∧ threshold(X,数额较大|情节严重|…)；①②③ 枚举的行为方式 → 析取
    exception        “不构成本罪 / 不以犯罪论处 …”节点 → 主规则中的 Naf
    conversion       “以 / 按 / 依照 Y 罪论处 / 定罪处罚”且 Y 是已知罪名 → constitutes(P,X,Y) ⇐ constitutes(P,X,c) ∧ 条件
    competition      “择一重 / 从一重 / 处罚较重的规定 / 数罪并罚” + 已知罪名 → 只记录罪名关系
    sentencing       “应当从重处罚 / 从重处罚” → Obligation(court)；“可以从轻 / 减轻” → Permission(court)
  跨罪名共享的谓词（minAge、mens、purpose、specialSubject、threshold、constitutes）与 crim_graph 的 cnv: 词表同前缀，
  因此两份文件可以合并推理；罪名个体用 cnj:c### 编号，名称见旁注 crim_jurex_glossary.json。
来源：每条规则 appliesSource = crime2article 中的《刑法》条文（AKN URI，2023 年文本），appliesAuthority = #jurex（专家标注）。
用法：../../../.venv/bin/python jurex2lrml.py
"""
import collections, hashlib, json, re
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
LR = HERE.parent.parent
OUT = HERE.parent / 'lrml'
L = 'http://docs.oasis-open.org/legalruleml/ns/v1.0/'
R = 'http://ruleml.org/spec'
NSMAP = {'lrml': L, 'ruleml': R, 'xs': 'http://www.w3.org/2001/XMLSchema',
         'xsi': 'http://www.w3.org/2001/XMLSchema-instance', 'lrmlv': L + 'metamodel#'}
AKN = '/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main#art_{}'
EL = {'犯罪客体': 'obj', '客观方面': 'oa', '犯罪主体': 'sub', '主观方面': 'sa'}
SPECIAL = [('国家机关工作人员', 'stateOrganStaff'), ('国家工作人员', 'stateFunctionary'), ('司法工作人员', 'judicialStaff'),
           ('军人', 'serviceman'), ('男子', 'male'), ('公司、企业', 'companyStaff'), ('邮政工作人员', 'postalStaff'),
           ('银行或者其他金融机构', 'financialStaff'), ('负有', 'dutyBearer'), ('依法', 'statutoryRole')]
PURPOSE = [('非法占有', 'illegalPossession'), ('营利', 'profit'), ('牟利', 'profit'), ('传播', 'dissemination'),
           ('出卖', 'sale'), ('勒索财物', 'ransom'), ('使用', 'use'), ('销售', 'sale'), ('报复', 'revenge'), ('勒索', 'extortion')]
THRESH = [('数额特别巨大', 'amountExtremelyHuge'), ('数额巨大', 'amountHuge'), ('数额较大', 'amountLarge'),
          ('情节特别严重', 'circumstancesExtremelySerious'), ('情节严重', 'circumstancesSerious'),
          ('情节恶劣', 'circumstancesVile'), ('严重后果', 'seriousConsequence')]
EXCL = re.compile(r'不构成(本罪|犯罪|该罪)|不以(本罪|犯罪)论处|不认为是犯罪|不成立本罪|不宜以本罪|不应认定为')
CONV = re.compile(r'(?:以|按|按照|依照)[^，。；]{0,24}?罪(?:的规定)?(?:论处|定罪处罚|定罪|处罚)')
COMP = re.compile(r'择一重|从一重|处罚较重的规定|数罪并罚')
HEAVY = re.compile(r'(?:应当)?从重处罚')
LIGHT = re.compile(r'可以(?:从轻|减轻|免除)')
ENUM = re.compile(r'^\s*[①②③④⑤⑥⑦⑧⑨⑩]|^\s*[（(][一二三四五六七八九十0-9]+[)）]')


def E(parent, tag, text=None, **attr):
    ns, name = tag.split(':')
    e = etree.SubElement(parent, f'{{{NSMAP[ns]}}}{name}', **attr) if parent is not None else etree.Element(f'{{{NSMAP[ns]}}}{name}', nsmap=NSMAP, **attr)
    if text is not None:
        e.text = text
    return e


def slug(s, pre):
    return pre + hashlib.md5(s.encode()).hexdigest()[:6]


class Lit:
    """(pred, args, neg)；args 中大写开头为变量，其他为个体。"""
    def __init__(self, pred, *args):
        self.pred, self.args = pred, args


def atom_xml(parent, lit, prefix):
    a = E(parent, 'ruleml:Atom')
    E(a, 'ruleml:Rel', iri=f'{prefix}:{lit.pred}')
    for x in lit.args:
        E(a, 'ruleml:Var' if x[:1].isupper() else 'ruleml:Ind', x)
    return a


def formula(parent, f):
    """f: ('and', [..]) / ('or', [..]) / ('naf', lit) / (prefix, Lit)"""
    kind = f[0]
    if kind in ('and', 'or'):
        if len(f[1]) == 1:
            return formula(parent, f[1][0])
        g = E(parent, 'ruleml:And' if kind == 'and' else 'ruleml:Or')
        for x in f[1]:
            formula(g, x)
        return g
    if kind == 'naf':
        return formula(E(parent, 'ruleml:Naf'), f[1])
    return atom_xml(parent, f[1], kind)


def walk(nodes, depth=0, path=()):
    for i, n in enumerate(nodes or []):
        yield n, depth, path + (i,)
        yield from walk(n.get('topics'), depth + 1, path + (i,))


def clean(t):
    return re.sub(r'【[TF]?\d{2}/[^】；]*[；】]?', '', t or '').strip()


def main():
    J = json.load(open(LR / 'lcr_jurex/data/jurex/jurex4e.json', encoding='utf-8'))
    c2a = json.load(open(LR / 'lcr_jurex/data/jurex/crime2article.json', encoding='utf-8'))
    law = json.load(open(LR / 'crim_graph/law/criminal_law_2023.json', encoding='utf-8'))
    crim_nodes = {n['clean'].strip(): n['id'] for n in json.load(open(LR / 'crim_graph/crim_nodes.json', encoding='utf-8'))
                  if n['clean'].strip().endswith('罪') and len(n['clean'].strip()) < 25}
    names = [list(x)[0] for x in J]
    known = sorted(set(names) | {k + '罪' for k in c2a}, key=len, reverse=True)   # 长名优先，避免“诈骗罪”吞掉“信用卡诈骗罪”
    ids = {n: f'c{i:03d}' for i, n in enumerate(names)}

    root = E(None, 'lrml:LegalRuleML')
    root.addprevious(etree.Comment(' 由 jurex2lrml.py 从 JUREX-4E 专家四要件生成，请勿手改。结构层无损；规则层为规则抽取，见 crim_jurex_glossary.json '))
    E(root, 'lrml:Prefix', key='cnv', refID='http://example.org/lexgo/crim-vocab#')
    E(root, 'lrml:Prefix', key='cnj', refID='http://example.org/lexgo/jurex-vocab#')
    srcs = E(root, 'lrml:LegalSources', key='legal-sources')
    arts_of, used_arts = {}, set()
    for n in names:
        arts = [a for a in c2a.get(n.rstrip('罪'), []) if str(a) in law]
        arts_of[n] = arts
        used_arts.update(arts)
    for a in sorted(used_arts):
        s = E(srcs, 'lrml:LegalSource', key=f'cl-art{a}', sameAs=AKN.format(a))
        E(s, 'lrml:Comment', f"《刑法》{law[str(a)]['label']}　" + ''.join(law[str(a)]['paras']))
    auths = E(root, 'lrml:Authorities', key='authorities')
    E(E(auths, 'lrml:Authority', key='jurex'), 'lrml:Comment', 'JUREX-4E 专家标注的犯罪构成四要件（法条 + 司法解释 + 学理），经规则抽取形式化')
    E(E(auths, 'lrml:Authority', key='npc'), 'lrml:Comment', '全国人民代表大会（《刑法》条文明文）')
    times = E(root, 'lrml:Times', key='times')
    t = etree.SubElement(times, f'{{{R}}}Time', key=':t-2024-03-01')
    d = etree.SubElement(t, f'{{{R}}}Data'); d.set(f'{{{NSMAP["xsi"]}}}type', 'xs:dateTime'); d.text = '2024-03-01T00:00:00Z'
    tc = E(E(root, 'lrml:TemporalCharacteristics', key='tb-cl2023'), 'lrml:TemporalCharacteristic')
    E(tc, 'lrml:forStatus', iri='lrmlv:Efficacious'); E(tc, 'lrml:hasStatusDevelopment', iri='lrmlv:Starts'); E(tc, 'lrml:atTime', keyref='#t-2024-03-01')
    assocs = E(root, 'lrml:Associations', key='associations')
    struct = E(root, 'lrml:Statements', key='jurex-structure')
    E(struct, 'lrml:Comment', 'JUREX-4E 专家四要件（结构层，无损）')
    rules_el = E(root, 'lrml:Statements', key='jurex-rules')
    E(rules_el, 'lrml:Comment', 'JUREX-4E 规则层（规则抽取）')

    gloss = {'charges': {}, 'predicates': {}, 'relations': [], 'stats': collections.Counter()}
    def pred(name, text):
        gloss['predicates'][name] = text
        return name

    def add_rule(key, body, heads, comment, n, prescriptive=None):
        """heads: [(prefix, Lit)]；prescriptive: ('Obligation'|'Permission')"""
        st = E(rules_el, 'lrml:PrescriptiveStatement' if prescriptive else 'lrml:ConstitutiveStatement', key=key)
        E(st, 'lrml:Comment', comment)
        rule = E(st, 'ruleml:Rule', closure='universal', key=':' + key)
        formula(E(rule, 'ruleml:if'), body)
        then = E(rule, 'ruleml:then')
        if prescriptive:
            sub = E(then, 'lrml:SuborderList')
            for i, (pfx, h) in enumerate(heads):
                op = E(sub, f'lrml:{prescriptive}', key=f'{key}-h{i}')
                E(op, 'lrml:Paraphrase', comment)
                slot = E(op, 'ruleml:slot'); E(slot, 'lrml:Bearer'); E(slot, 'ruleml:Ind', 'court')
                atom_xml(op, h, pfx)
        else:
            formula(then, ('and', [(p, h) for p, h in heads]))
        a = E(assocs, 'lrml:Association')
        for art in arts_of[n]:
            E(a, 'lrml:appliesSource', keyref=f'#cl-art{art}')
        E(a, 'lrml:appliesAuthority', keyref='#jurex')
        E(a, 'lrml:appliesTemporalCharacteristics', keyref='#tb-cl2023')
        E(a, 'lrml:appliesStrength', iri='lrmlv:Defeasible')
        E(a, 'lrml:toTarget', keyref='#' + key)
        gloss['stats'][('prescriptive' if prescriptive else 'constitutive')] += 1

    for x in J:
        n = list(x)[0]; cid = ids[n]; tree = x[n]
        gloss['charges'][cid] = {'name': n, 'articles': arts_of[n], 'crim_graph_node': crim_nodes.get(n)}
        cs = E(struct, 'lrml:Statements', key=f'jx-{cid}')
        E(cs, 'lrml:Comment', n + (f'（crim_graph 节点 {crim_nodes[n]}）' if n in crim_nodes else ''))
        conds, excs = {}, []
        for el, code in EL.items():
            es = E(cs, 'lrml:Statements', key=f'jx-{cid}-{code}')
            E(es, 'lrml:Comment', el)
            stack = {(): es}
            for node, depth, path in walk(tree.get(el)):
                txt = clean(node.get('title', ''))
                parent = stack[path[:-1]]
                k = f'jx-{cid}-{code}-' + '.'.join(map(str, path))
                if node.get('topics'):
                    s = E(parent, 'lrml:Statements', key=k); stack[path] = s
                else:
                    s = E(parent, 'lrml:FactualStatement', key=k)
                E(s, 'lrml:Comment', txt or '（空）')
                gloss['stats']['structure_nodes'] += 1
            top = clean(' '.join(nd.get('title', '') for nd in tree.get(el, [])))
            alltxt = [(clean(nd.get('title', '')), path, nd) for nd, _, path in walk(tree.get(el))]
            # ---------------- 要件谓词的定义规则
            P, X = 'P', 'X'
            if code == 'sub':
                lits = []
                ages = [int(a) for t, _, _ in alltxt[:3] for a in re.findall(r'(?:年满|已满|满)\s*(\d+)\s*周岁', t)]
                if ages:
                    lits.append(('cnv', Lit('minAge', P, f'age{min(ages)}'))); gloss['stats']['age'] += 1
                sp = [s for kw, s in SPECIAL if kw in top]
                if '特殊主体' in top or sp:
                    for s in (sp or ['other']):
                        lits.append(('cnv', Lit('specialSubject', P, s)))
                    gloss['stats']['special_subject'] += 1
                elif '一般主体' in top:
                    lits.append(('cnv', Lit('generalSubject', P))); gloss['stats']['general_subject'] += 1
                if not lits:
                    lits.append(('cnj', Lit(pred(f'{cid}_sub', top), P)))
                body = ('and', lits)
                head2 = re.sub(r'[【】*]', '', '｜'.join(t for t, _, path in alltxt if len(path) <= 2))   # 节点之间加分隔符，避免跨节点匹配
                if re.search(r'只能是单位|仅限于单位', head2):
                    body = ('and', [('cnv', Lit('unitSubject', P))]); gloss['stats']['unit_only'] += 1
                elif re.search(r'(?:自然人|个人)[、，,和及也包括\s]*单位(?!组织)|单位(?:也|亦)?(?:可以|可)(?:成立|构成|成为)|包括单位|单位和个人|单位犯', head2):
                    body = ('or', [body, ('cnv', Lit('unitSubject', P))]); gloss['stats']['unit_subject'] += 1
                add_rule(f'jx-{cid}-r-sub', body, [('cnj', Lit(pred(f'{cid}_subject', f'{n}·犯罪主体'), P))], f'{n}：犯罪主体', n)
            elif code == 'sa':
                lits = []
                m = 'directIntent' if '直接故意' in top else 'negligence' if ('过失' in top and '故意' not in top) else 'intent' if '故意' in top else None
                if m:
                    lits.append(('cnv', Lit('mens', P, X, m))); gloss['stats']['mens_' + m] += 1
                if '明知' in top:
                    lits.append(('cnv', Lit('knowledge', P, X))); gloss['stats']['knowledge'] += 1
                for mm in re.finditer(r'(?:以|具有|出于)([^，。、；]{2,16}?)(?:为目的|的目的|目的)', top):
                    hit = next(((k, v) for k, v in PURPOSE if k in mm.group(1)), None)
                    s = hit[1] if hit else slug(mm.group(1), 'p')
                    pred(s, hit[0] if hit else mm.group(1))   # 共享谓词用规范名，避免被后处理的罪名覆盖
                    lits.append(('cnv', Lit('purpose', P, X, s))); gloss['stats']['purpose'] += 1
                if not lits:
                    lits.append(('cnj', Lit(pred(f'{cid}_sa', top), P, X)))
                add_rule(f'jx-{cid}-r-sa', ('and', lits), [('cnj', Lit(pred(f'{cid}_subjective', f'{n}·主观方面'), P, X))], f'{n}：主观方面', n)
            elif code == 'obj':
                add_rule(f'jx-{cid}-r-obj', ('and', [('cnj', Lit(pred(f'{cid}_interest', top), X))]),
                         [('cnj', Lit(pred(f'{cid}_object', f'{n}·犯罪客体'), X))], f'{n}：犯罪客体（{top[:40]}）', n)
            elif code == 'oa':
                head = tree.get(el, [{}])[0]
                lits = [('cnj', Lit(pred(f'{cid}_conduct', clean(head.get('title', ''))), P, X))]
                th = [v for k, v in THRESH if k in clean(head.get('title', ''))]
                for v in th[:1]:
                    lits.append(('cnv', Lit('threshold', X, v))); gloss['stats']['threshold'] += 1
                add_rule(f'jx-{cid}-r-oa', ('and', lits), [('cnj', Lit(pred(f'{cid}_objective', f'{n}·客观方面'), P, X))], f'{n}：客观方面', n)
                # 枚举的行为方式：父节点 ⇐ 子项析取
                for nd, _, path in walk(tree.get(el)):
                    kids = [c for c in nd.get('topics') or [] if ENUM.match(c.get('title', ''))]
                    if len(kids) >= 2:
                        parent_p = f'{cid}_oa_' + '_'.join(map(str, path))
                        pred(parent_p, clean(nd.get('title', '')))
                        alts = [('cnj', Lit(pred(f'{parent_p}_{j}', clean(c.get('title', ''))), P, X)) for j, c in enumerate(kids)]
                        add_rule(f'jx-{cid}-r-enum-' + '.'.join(map(str, path)), ('or', alts), [('cnj', Lit(parent_p, P, X))],
                                 f'{n}：{clean(nd.get("title", ""))[:30]}（{len(kids)} 种方式择一）', n)
                        gloss['stats']['enumerations'] += 1
            # ---------------- 例外 / 转化 / 竞合 / 量刑（遍历该要件下全部节点）
            for txt, path, nd in alltxt:
                if EXCL.search(txt):
                    p = pred(f'{cid}_exc_{code}_' + '_'.join(map(str, path)), txt)
                    excs.append(('naf', ('cnj', Lit(p, P, X)))); gloss['stats']['exceptions'] += 1
                others = [o for o in known if o != n and o in txt]
                others = [o for o in others if not any(o != q and o in q for q in others)]   # 去掉被更长罪名包含的
                conv_targets = []
                for mm in re.finditer(r'(?:以|按|按照|依照)((?:[^，。；、以按依]{1,24}?罪、)*[^，。；、以按依]{1,24}?罪)(?:的规定)?(?:论处|定罪处罚|定罪|处罚)', txt):
                    for part in mm.group(1).split('、'):
                        hit = next((o for o in known if o == part or (part.endswith(o) and len(part) - len(o) <= 2)), None)
                        if hit and hit != n:
                            conv_targets.append(hit)
                if conv_targets:
                    for o in dict.fromkeys(conv_targets):
                        oc = ids.get(o) or slug(o, 'x')
                        if oc not in ids.values():
                            pred(oc, o)
                        p = pred(f'{cid}_conv_{code}_' + '_'.join(map(str, path)), txt)
                        add_rule(f'jx-{cid}-r-conv-{oc}-' + '.'.join(map(str, path)),
                                 ('and', [('cnv', Lit('constitutes', P, X, cid)), ('cnj', Lit(p, P, X))]),
                                 [('cnv', Lit('constitutes', P, X, oc))], f'{n} → {o}（转化 / 依{o}论处）：{txt[:50]}', n)
                        gloss['relations'].append({'from': n, 'to': o, 'type': 'conversion', 'text': txt})
                        gloss['stats']['conversions'] += 1
                elif others and COMP.search(txt):
                    for o in others[:3]:
                        gloss['relations'].append({'from': n, 'to': o, 'type': 'competition', 'text': txt})
                        gloss['stats']['competitions'] += 1
                if HEAVY.search(txt) and '不' not in txt[:4]:
                    p = pred(f'{cid}_aggr_{code}_' + '_'.join(map(str, path)), txt)
                    add_rule(f'jx-{cid}-r-heavy-' + code + '.' + '.'.join(map(str, path)),
                             ('and', [('cnv', Lit('responsible', P, X, cid)), ('cnj', Lit(p, P, X))]),
                             [('cnv', Lit('sentence', P, X, 'heavier'))], f'{n}：{txt[:40]}', n, prescriptive='Obligation')
                    gloss['stats']['heavier'] += 1
                elif LIGHT.search(txt):
                    p = pred(f'{cid}_mitig_{code}_' + '_'.join(map(str, path)), txt)
                    add_rule(f'jx-{cid}-r-light-' + code + '.' + '.'.join(map(str, path)),
                             ('and', [('cnv', Lit('responsible', P, X, cid)), ('cnj', Lit(p, P, X))]),
                             [('cnv', Lit('sentence', P, X, 'lighterOrReduced'))], f'{n}：{txt[:40]}', n, prescriptive='Permission')
                    gloss['stats']['lighter'] += 1
        # ---------------- 四要件合取（主规则）
        body = [('cnj', Lit(f'{cid}_object', 'X')), ('cnj', Lit(f'{cid}_objective', 'P', 'X')),
                ('cnj', Lit(f'{cid}_subject', 'P')), ('cnj', Lit(f'{cid}_subjective', 'P', 'X'))] + excs
        add_rule(f'jx-{cid}-r-main', ('and', body), [('cnv', Lit('constitutes', 'P', 'X', cid))],
                 f'{n}：犯罪构成 = 客体 ∧ 客观方面 ∧ 主体 ∧ 主观方面' + (f'，除非 {len(excs)} 项出罪情形' if excs else ''), n)
        pred(cid, n)
        gloss['stats']['charges'] += 1
        gloss['stats']['charges_with_articles'] += bool(arts_of[n])
        gloss['stats']['charges_linked_to_crim_graph'] += n in crim_nodes

    OUT.mkdir(exist_ok=True)
    path = OUT / 'crim_jurex.lrml'
    etree.ElementTree(root).write(str(path), xml_declaration=True, encoding='UTF-8', pretty_print=True)
    schema = etree.XMLSchema(etree.parse(str(LR / 'civil_graph/schema/lrml-compact.xsd')))
    ok = schema.validate(etree.parse(str(path)))
    gloss['stats'] = dict(gloss['stats']); gloss['stats']['xsd_valid'] = ok
    gloss['stats']['legal_sources'] = len(used_arts)
    json.dump(gloss, open(OUT / 'crim_jurex_glossary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(gloss['stats'], ensure_ascii=False, indent=1))
    if not ok:
        print('\n'.join(str(e) for e in list(schema.error_log)[:5]))


if __name__ == '__main__':
    main()
