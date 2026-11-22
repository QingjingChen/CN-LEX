#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能评估：用 SPARQL 回答 CN-LRML 的能力问题（Competency Questions），并与预先写定的期望答案核对。

期望答案在写查询之前根据条文确定（例如第1199条的过错推定被第1201条的补充责任规则优先）。
“通过” = 查询返回结果且包含全部期望答案。另报每个 CQ 的答案数量与前几行，供论文引用。
用法：../../../.venv/bin/python cq_eval.py   → results/cq_results.json、queries/cq*.rq
"""
import json
from pathlib import Path
from rdflib import Graph

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PFX = """PREFIX clx: <http://example.org/clexml/ontology#>
PREFIX norm: <http://example.org/clexml/norm/>
PREFIX pred: <http://example.org/clexml/pred/>
PREFIX off:  <http://example.org/clexml/offence/>
PREFIX auth: <http://example.org/clexml/authority/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

CQS = [
    ('CQ1', 'Provenance', 'Which norms are grounded in Civil Code art. 1199, under which authority and strength?',
     """SELECT ?norm ?auth ?strength WHERE {
  ?norm clx:sourceProvision ?p ; clx:authority ?auth ; clx:strength ?strength .
  FILTER(STRENDS(STR(?p), "civil-code/zho@/!main#art_1199")) }""",
     ['civil/c1199']),
    ('CQ2', 'Principle-exception', 'Which norms override the school-liability norm of art. 1199, and on which provisions do they rest?',
     """SELECT ?over ?prov WHERE {
  ?over clx:overrides <http://example.org/clexml/norm/civil/c1199> ; clx:sourceProvision ?prov . }""",
     ['civil/c1201-supp', 'art_1201']),
    ('CQ3', 'Exception conditions', 'Which civil norms carry an "unless" (Naf) condition, and which norm can establish that condition?',
     """SELECT ?norm ?cond ?supplier WHERE {
  ?norm clx:code "civil" ; clx:hasExceptionCondition ?cond .
  OPTIONAL { ?supplier clx:exceptionTo ?norm ; clx:hasEffect ?cond . } }""",
     ['civil/c1199', 'provesDutyFulfilled']),
    ('CQ4', 'Offence elements', 'What are the four constituent elements of theft (盗窃罪) and on which article is it grounded?',
     """SELECT ?object ?objective ?subject ?subjective ?art WHERE {
  off:盗窃罪 clx:hasObject ?object ; clx:hasObjectiveAspect ?objective ;
          clx:hasSubject ?subject ; clx:hasSubjectiveAspect ?subjective ; clx:groundedIn ?art . }""",
     ['art_264', '公私财产所有权']),
    ('CQ5', 'Offence relations', 'Which offences are related to robbery (抢劫罪) by conversion or demarcation?',
     """SELECT DISTINCT ?other WHERE {
  { off:抢劫罪 clx:relatedOffence ?other } UNION { ?other clx:relatedOffence off:抢劫罪 } }""",
     ['盗窃罪', '抢夺罪']),
    ('CQ6', 'Authority', 'Which rule-layer assertions rest on doctrine or judicial interpretation rather than statutory text?',
     """SELECT ?code ?auth (COUNT(?norm) AS ?n) WHERE {
  ?norm clx:authority ?auth ; clx:code ?code . FILTER(?auth IN (auth:doctrine, auth:spc)) }
GROUP BY ?code ?auth ORDER BY ?code ?auth""",
     ['doctrine', 'spc']),
    ('CQ7', 'Deontic addressee', 'Which sentencing norms of the Criminal Law are obligations, permissions or prohibitions addressed to the court?',
     """SELECT ?mode (COUNT(?norm) AS ?n) WHERE {
  ?norm a clx:PrescriptiveNorm ; clx:code "criminal" ; clx:bearer "court" ; clx:deonticMode ?mode . }
GROUP BY ?mode ORDER BY ?mode""",
     ['Obligation', 'Permission', 'Prohibition']),
    ('CQ8', 'Multi-hop dependency', 'Which provisions must be consulted, transitively, to apply the will-validity norm grounded in art. 1143?',
     """SELECT DISTINCT ?prov WHERE {
  ?n clx:sourceProvision ?p . FILTER(CONTAINS(STR(?p), "civil-code/zho@/!main#art_1143"))
  ?n clx:dependsOn+ ?m . ?m clx:sourceProvision ?prov . }""",
     ['art_19']),
    ('CQ9', 'Version anchoring', 'Which criminal norms rest on provisions inserted by later amendments (第N条之M) of the consolidated 2023 text?',
     """SELECT DISTINCT ?norm ?prov WHERE {
  ?norm clx:code "criminal" ; clx:sourceProvision ?prov .
  FILTER(REGEX(STR(?prov), "zho@2023-12-29/!main#art_[0-9]+_[0-9]+$")) }""",
     ['art_17_1']),
    ('CQ10', 'Coverage gap', 'Which offences have constituent elements in the structure layer but no rule-layer norm on their article yet?',
     """SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {
  ?o a clx:Offence ; clx:groundedIn ?a .
  FILTER NOT EXISTS { ?norm clx:sourceProvision ?a ; clx:code "criminal" .
                      FILTER NOT EXISTS { ?norm a clx:TaxonomicNorm } } }""",
     []),
    ('CQ11', 'Unit subject (JUREX)', 'Which offences can be committed by a unit (单位)?',
     """SELECT DISTINCT ?c WHERE {
  ?n clx:layer "criminal_jurex" ; clx:hasCondition pred:unitSubject ; rdfs:comment ?c . }""",
     ['生产、销售伪劣产品罪']),
    ('CQ12', 'Exception link (cards)', 'Which civil norms record an exception or priority relation to Civil Code art. 725?',
     """SELECT DISTINCT ?n ?t WHERE {
  { ?n clx:exceptionLink ?a } UNION { ?n clx:priorityLink ?a }
  FILTER(STRENDS(STR(?a), "civil-code/zho@/!main#art_725")) ?n rdfs:label ?t . }""",
     ['物权']),
    ('CQ13', 'Purpose element (JUREX)', 'Which offences require a specific purpose in their subjective aspect?',
     """SELECT DISTINCT ?c WHERE {
  ?n clx:layer "criminal_jurex" ; clx:hasCondition pred:purpose ; rdfs:comment ?c . }""",
     ['盗窃罪']),
]


def main():
    g = Graph().parse(ROOT / 'resources' / 'rdf' / 'cn_lex.ttl', format='turtle')
    (ROOT / 'queries').mkdir(exist_ok=True)
    out = []
    for cid, theme, q, sparql, expect in CQS:
        (ROOT / 'queries' / f'{cid.lower()}.rq').write_text(f'# {cid} {theme}: {q}\n' + PFX + sparql + '\n', encoding='utf-8')
        rows = [[str(v) if v is not None else '' for v in r] for r in g.query(PFX + sparql)]
        flat = ' '.join(' '.join(r) for r in rows)
        ok = bool(rows) and all(e in flat for e in expect)
        out.append({'id': cid, 'theme': theme, 'question': q, 'n_answers': len(rows), 'pass': ok,
                    'expected': expect, 'sample': rows[:6]})
        print(f'{cid:5s} {theme:22s} answers={len(rows):4d}  {"PASS" if ok else "FAIL"}  {rows[:2]}')
    print(f'passed {sum(x["pass"] for x in out)}/{len(out)}')
    json.dump(out, open(ROOT / 'queries' / 'cq_results.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
