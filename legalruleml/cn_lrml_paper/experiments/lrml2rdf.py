#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CN-LRML：把民法 / 刑法 LegalRuleML（XML，XSD 校验）导出为 RDF 知识图谱，并做功能评估前的检查。

只读取 .lrml 文件本身（加上刑法四要件知识库 lrml_kb.json，它的每个字段都指向 crim_graph.lrml 的 Statement 键），
因此图谱中的每条断言都能回溯到 LegalRuleML 元素与 Akoma Ntoso 条文 URI。

词表（cnlr:，拟议本体；与 LegalRuleML 元模型 lrmlmm:、PROV-O 对齐）：
  cnlr:Provision           AKN 条/款（IRI 即 AKN URI）；cnlr:code、rdfs:label、cnlr:text
  cnlr:Norm                LegalRuleML 规则（lrmlmm:Statement）；子类 ConstitutiveNorm / PrescriptiveNorm / TaxonomicNorm
     cnlr:hasCondition     条件谓词            cnlr:hasExceptionCondition  Naf 谓词（“除非 / 但是”）
     cnlr:hasEffect        结论谓词            cnlr:deonticMode            Obligation / Permission / Prohibition / Right / Constitutive
     cnlr:bearer           道义承担者           cnlr:negatedEffect          结论为强否定
     cnlr:sourceProvision  appliesSource       cnlr:authority              npc / spc / doctrine / graph
     cnlr:strength         Defeasible / Strict  cnlr:module                规则模块
     cnlr:overrides        Override(over, under)
     cnlr:exceptionTo      r' 的结论 = r 的 Naf 谓词（派生；prov:wasDerivedFrom 记录依据）
     cnlr:dependsOn        r' 的结论 = r 的条件谓词（派生）
  cnlr:Offence             罪名；cnlr:hasObject / hasObjectiveAspect / hasSubject / hasSubjectiveAspect（四要件），
                           cnlr:groundedIn（条文），cnlr:relatedOffence（此罪与彼罪 / 转化，取自结构层 conv 节点），
                           cnlr:structureNode（crim_graph.lrml 中的节点键）
用法：../../../.venv/bin/python lrml2rdf.py   → kg/cn_lrml.ttl、results/kg_stats.json
"""
import collections, json, re, sys
from pathlib import Path
from lxml import etree
from rdflib import Graph, Literal, Namespace, URIRef, RDF, RDFS, OWL
from rdflib.namespace import PROV, XSD

HERE = Path(__file__).resolve().parent
LR = HERE.parent.parent
L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
R = '{http://ruleml.org/spec}'
CNLR = Namespace('http://example.org/clexml/ontology#')
NORM = Namespace('http://example.org/clexml/norm/')
PRED = Namespace('http://example.org/clexml/pred/')
OFF = Namespace('http://example.org/clexml/offence/')
AUTH = Namespace('http://example.org/clexml/authority/')
LRMLMM = Namespace('http://docs.oasis-open.org/legalruleml/ns/v1.0/metamodel#')
AKN = 'http://example.org'              # AKN URI 前缀：http://example.org/akn/cn/act/...
FILES = {'civil': ('civil', LR / 'civil_graph' / 'civil_graph.lrml'),
         'criminal': ('criminal', LR / 'crim_graph' / 'crim_graph.lrml'),
         'civil_cards': ('civil', HERE.parent / 'lrml' / 'civil_cards.lrml'),          # ExpertGraph 全量 409 张 card
         'criminal_jurex': ('criminal', HERE.parent / 'lrml' / 'crim_jurex.lrml')}     # JUREX-4E 155 个罪名四要件
FET = {'犯罪客体': CNLR.hasObject, '客观方面': CNLR.hasObjectiveAspect, '犯罪主体': CNLR.hasSubject, '主观方面': CNLR.hasSubjectiveAspect}


def modules():
    out = {}
    for d, mod in (('civil_graph', 'formal_rules'), ('crim_graph', 'crim_rules')):
        sys.path.insert(0, str(LR / d))
        m = __import__(mod)
        for k, (title, rules) in m.MODULES.items():
            for r in rules:
                out[r['key']] = title
        sys.path.pop(0)
        sys.modules.pop(mod, None)
    return out


def rel(atom):
    r = atom.find(R + 'Rel')
    return r.get('iri').split(':', 1)[1] if r is not None else None


def xsd_ok(path):
    schema = etree.XMLSchema(etree.parse(str(LR / 'civil_graph' / 'schema' / 'lrml-compact.xsd')))
    ok = schema.validate(etree.parse(str(path)))
    return ok, [str(e) for e in schema.error_log][:3]


def main():
    g = Graph()
    for p, ns in (('clx', CNLR), ('norm', NORM), ('pred', PRED), ('off', OFF), ('auth', AUTH), ('lrmlmm', LRMLMM), ('prov', PROV)):
        g.bind(p, ns)
    # ---- 本体声明（TBox）
    for c, sup in ((CNLR.Norm, LRMLMM.Statement), (CNLR.ConstitutiveNorm, CNLR.Norm), (CNLR.PrescriptiveNorm, CNLR.Norm),
                   (CNLR.TaxonomicNorm, CNLR.ConstitutiveNorm), (CNLR.Provision, LRMLMM.LegalSource),
                   (CNLR.Predicate, OWL.Thing), (CNLR.Offence, OWL.Thing), (CNLR.Authority, LRMLMM.Authority)):
        g.add((c, RDF.type, OWL.Class)); g.add((c, RDFS.subClassOf, sup))
    for p, dom, rng in ((CNLR.hasCondition, CNLR.Norm, CNLR.Predicate), (CNLR.hasExceptionCondition, CNLR.Norm, CNLR.Predicate),
                        (CNLR.hasEffect, CNLR.Norm, CNLR.Predicate), (CNLR.sourceProvision, CNLR.Norm, CNLR.Provision),
                        (CNLR.authority, CNLR.Norm, CNLR.Authority), (CNLR.overrides, CNLR.Norm, CNLR.Norm),
                        (CNLR.exceptionTo, CNLR.Norm, CNLR.Norm), (CNLR.dependsOn, CNLR.Norm, CNLR.Norm),
                        (CNLR.groundedIn, CNLR.Offence, CNLR.Provision), (CNLR.relatedOffence, CNLR.Offence, CNLR.Offence)):
        g.add((p, RDF.type, OWL.ObjectProperty)); g.add((p, RDFS.domain, dom)); g.add((p, RDFS.range, rng))
    g.add((CNLR.overrides, RDFS.subPropertyOf, LRMLMM.overrides))
    g.add((CNLR.relatedOffence, RDF.type, OWL.SymmetricProperty))

    mods = modules()
    stats = {}
    for label, (code, path) in FILES.items():
        ok, errs = xsd_ok(path)
        root = etree.parse(str(path)).getroot()
        src_iri = {}
        for s in root.iter(L + 'LegalSource'):
            same = s.get('sameAs')
            iri = URIRef(AKN + same) if same.startswith('/akn') else URIRef(same)
            src_iri[s.get('key')] = iri
            g.add((iri, RDF.type, CNLR.Provision)); g.add((iri, CNLR.code, Literal(code)))
            c = s.find(L + 'Comment')
            if c is not None:
                txt = c.text or ''
                m = re.match(r'(《[^》]+》第[^　：:]+?(?:条之[一二三四五六七八九十]+|条)(?:第\d+款)?)', txt)
                g.add((iri, RDFS.label, Literal(m.group(1) if m else txt[:20], lang='zh')))
                g.add((iri, CNLR.text, Literal(txt, lang='zh')))
        assoc = collections.defaultdict(lambda: collections.defaultdict(set))
        for a in root.iter(L + 'Association'):
            tg = [t.get('keyref').lstrip('#') for t in a.findall(L + 'toTarget')]
            for t in tg:
                for s in a.findall(L + 'appliesSource'):
                    assoc[t]['src'].add(s.get('keyref').lstrip('#'))
                for s in a.findall(L + 'appliesAuthority'):
                    assoc[t]['auth'].add(s.get('keyref').lstrip('#'))
                for s in a.findall(L + 'appliesStrength'):
                    assoc[t]['strength'].add(s.get('iri').split(':')[-1])
        norms, produces, uses = {}, collections.defaultdict(set), []
        n_isa = 0
        for st in root.iter(L + 'ConstitutiveStatement', L + 'PrescriptiveStatement'):
            k = st.get('key')
            rule = st.find(R + 'Rule')
            isa = k.startswith('isa') or (st.find(L + 'Comment') is not None and 'isA' in (st.find(L + 'Comment').text or '') and k.startswith('i'))
            n = NORM[f'{code}/{k}']
            norms[k] = n
            kind = CNLR.PrescriptiveNorm if st.tag == L + 'PrescriptiveStatement' else CNLR.ConstitutiveNorm
            conds, excs = [], []
            ifp = rule.find(R + 'if')
            if ifp is not None:
                for at in ifp.iter(R + 'Atom'):
                    p = rel(at)
                    inside_naf = any(anc.tag == R + 'Naf' for anc in at.iterancestors())
                    (excs if inside_naf else conds).append(p)
            heads, modes, bearer, negh = [], set(), None, False
            then = rule.find(R + 'then')
            for at in then.iter(R + 'Atom'):
                heads.append(rel(at))
                if any(anc.tag == R + 'Neg' for anc in at.iterancestors()):
                    negh = True
            for dm in ('Obligation', 'Permission', 'Prohibition', 'Right'):
                for e in then.iter(L + dm):
                    modes.add(dm)
                    b = e.find(f'{R}slot/{R}Ind')
                    if b is not None:
                        bearer = b.text
            src = assoc[k]['src'] | assoc[k[1:] if k.startswith(':') else k]['src']
            auth = assoc[k]['auth']
            if 'graph' in auth:
                kind = CNLR.TaxonomicNorm; n_isa += 1
            g.add((n, RDF.type, kind)); g.add((n, CNLR.code, Literal(code))); g.add((n, CNLR.layer, Literal(label)))
            cm = st.find(L + 'Comment')
            if cm is not None and cm.text:
                g.add((n, RDFS.comment, Literal(cm.text, lang='zh')))
            g.add((n, CNLR.deonticMode, Literal('|'.join(sorted(modes)) or 'Constitutive')))
            if bearer:
                g.add((n, CNLR.bearer, Literal(bearer)))
            if negh:
                g.add((n, CNLR.negatedEffect, Literal(True)))
            for p in conds:
                g.add((n, CNLR.hasCondition, PRED[p]))
            for p in excs:
                g.add((n, CNLR.hasExceptionCondition, PRED[p]))
            for p in heads:
                g.add((n, CNLR.hasEffect, PRED[p])); produces[p].add(k)
            for s in src:
                if s in src_iri:
                    g.add((n, CNLR.sourceProvision, src_iri[s]))
            for a in auth:
                g.add((n, CNLR.authority, AUTH[a]))
            for s in assoc[k]['strength']:
                g.add((n, CNLR.strength, Literal(s)))
            if k in mods:
                g.add((n, CNLR.module, Literal(mods[k], lang='zh')))
            if kind != CNLR.TaxonomicNorm:
                uses.append((k, conds, excs))
        for p in set(produces):
            g.add((PRED[p], RDF.type, CNLR.Predicate))
        n_ov = 0
        for o in root.iter(L + 'Override'):
            a, b = o.get('over').lstrip('#'), o.get('under').lstrip('#')
            if a in norms and b in norms:
                g.add((norms[a], CNLR.overrides, norms[b])); n_ov += 1
        n_exc = n_dep = 0
        for k, conds, excs in uses:
            for p in excs:
                for k2 in produces.get(p, ()):
                    if k2 != k:
                        g.add((norms[k2], CNLR.exceptionTo, norms[k])); n_exc += 1
            for p in conds:
                for k2 in produces.get(p, ()):
                    if k2 != k and norms[k2] in norms.values():
                        g.add((norms[k], CNLR.dependsOn, norms[k2])); n_dep += 1
        mine = set(norms.values())
        stats[label] = {'xsd_valid': ok, 'xsd_errors': errs, 'provisions': len(src_iri), 'norms': len(norms),
                       'taxonomic': n_isa, 'rule_layer': len(norms) - n_isa, 'overrides': n_ov,
                       'exceptionTo(derived)': sum(1 for a, b in g.subject_objects(CNLR.exceptionTo) if a in mine),
                       'dependsOn(derived)': sum(1 for a, b in g.subject_objects(CNLR.dependsOn) if a in mine),
                       'predicates': len({p for _, cs, es in uses for p in cs + es} | set(produces)),
                       'rules_with_naf': sum(1 for _, _, e in uses if e),
                       'statements_structure': sum(1 for _ in root.iter(L + 'Statements', L + 'FactualStatement'))}

    # ---- 刑法罪名四要件（结构层）
    kb = json.load(open(LR / 'lcr_jurex' / 'data' / 'lrml_kb.json', encoding='utf-8'))
    c2a = json.load(open(LR / 'lcr_jurex' / 'data' / 'jurex' / 'crime2article.json', encoding='utf-8'))
    n_fet = 0
    for c, k in kb.items():
        o = OFF[c]
        g.add((o, RDF.type, CNLR.Offence)); g.add((o, RDFS.label, Literal(c, lang='zh')))
        g.add((o, CNLR.structureNode, Literal(k['node'])))
        if k.get('concept'):
            g.add((o, RDFS.comment, Literal(k['concept'], lang='zh')))
        for f, prop in FET.items():
            if k['fet'].get(f):
                g.add((o, prop, Literal(k['fet'][f], lang='zh'))); n_fet += 1
        for a in c2a.get(c.rstrip('罪'), []):
            g.add((o, CNLR.groundedIn, URIRef(f'{AKN}/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main#art_{a}')))
        for x in k['conditions']:
            if x['type'] == 'conv':
                for d in kb:
                    if d != c and d.rstrip('罪') in x['text']:
                        g.add((o, CNLR.relatedOffence, OFF[d]))
                        g.add((o, PROV.wasDerivedFrom, Literal(x['id'])))
    # ---- JUREX-4E 罪名（crim_jurex.lrml）：Offence 由主规则定义；转化 / 竞合关系
    gj = json.load(open(HERE.parent / 'lrml' / 'crim_jurex_glossary.json', encoding='utf-8'))
    for cid, info in gj['charges'].items():
        o = OFF[info['name']]
        g.add((o, RDF.type, CNLR.Offence)); g.add((o, RDFS.label, Literal(info['name'], lang='zh')))
        g.add((o, CNLR.definedBy, NORM[f'criminal/jx-{cid}-r-main']))
        for a in info['articles']:
            g.add((o, CNLR.groundedIn, URIRef(f'{AKN}/akn/cn/act/1997-03-14/criminal-law/zho@2023-12-29/!main#art_{a}')))
    for r in gj['relations']:
        g.add((OFF[r['from']], CNLR.relatedOffence, OFF[r['to']]))
        g.add((OFF[r['from']], CNLR.convertsTo if r['type'] == 'conversion' else CNLR.concurrentWith, OFF[r['to']]))
    # ---- ExpertGraph card 的规范链接（只含写明目标的语句）
    gc = json.load(open(HERE.parent / 'lrml' / 'civil_cards_glossary.json', encoding='utf-8'))
    prop = {'exception': CNLR.exceptionLink, 'priority': CNLR.priorityLink, 'related': CNLR.relatedNorm, 'distinguish': CNLR.distinguishedFrom}
    for r in gc['relations']:
        tgt = NORM[f"civil/{r['to']}"] if r['to_type'] == 'card' else URIRef(f"{AKN}/akn/cn/act/2020-05-28/civil-code/zho@/!main#art_{r['to']}")
        g.add((NORM[f"civil/{r['from']}"], prop[r['type']], tgt))
    for k, v in gc['cards'].items():
        g.add((NORM[f'civil/{k}'], RDFS.label, Literal(v['title'], lang='zh')))
        for fk in v['formalisedBy']:
            g.add((NORM[f'civil/{k}'], CNLR.formalisedBy, NORM[f'civil/{fk}']))
    stats['criminal']['offences'] = len(kb)
    stats['criminal']['offence_elements'] = n_fet
    stats['offences_total'] = len(set(g.subjects(RDF.type, CNLR.Offence)))
    stats['offence_relations_total'] = len({frozenset(x) for x in g.subject_objects(CNLR.relatedOffence)})
    stats['card_links'] = {str(p).split('#')[-1]: len(list(g.subject_objects(p))) for p in prop.values()}
    stats['triples'] = len(g)
    (HERE / 'kg').mkdir(exist_ok=True); (HERE / 'results').mkdir(exist_ok=True)
    g.serialize(HERE / 'kg' / 'cn_lrml.ttl', format='turtle')
    json.dump(stats, open(HERE / 'results' / 'kg_stats.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
