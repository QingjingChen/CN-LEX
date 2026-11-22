# CN-LEX

The Chinese Civil Code and Criminal Law in Akoma Ntoso, LegalRuleML and RDF, with the materials of the paper
*CN-LEX: From Chinese Legal Knowledge Representation to Downstream AI Applications*. Every rule is bound to its
provision through `lrml:LegalSource/@sameAs`, an Akoma Ntoso URI such as
`/akn/cn/act/2020-05-28/civil-code/zho@/!main#art_145`. Drafted rules carry `pending_expert_review`.

| Paper | Path | |
|---|---|---|
| Sect. 3 | `resources/civil/`, `resources/criminal/` | expert outlines with hand-written rules (`*_graph.lrml`), converted expert resources (`civil_cards.lrml`, `crim_jurex.lrml`), review-stage exports (`*_review.lrml`: 3,389 civil and 2,875 criminal rules) |
| Sect. 3 | `resources/rdf/`, `queries/` | RDF graph and 13 SPARQL competency questions |
| Sect. 4 | `studies/extraction/` | expert review of 18 rows (102 rules) |
| Sect. 5 | `studies/retrieval/` | retrieval results; disjunctions lost in verbalised rules |
| Sect. 6 | `reasoning/`, `studies/reasoning/` | rules compiled to defeasible deontic logic (ASP), scenarios, item 526 |

## Use

`cn_onto.py` needs only the Python standard library:

```sh
python cn_onto.py stats                       # rules, overrides and candidate relations
python cn_onto.py article 145                 # rules of an article, with RuleML and directed overrides
python cn_onto.py export --law civil --output civil_rules.jsonl
python cn_onto.py validate                    # hashes, counts, references, override direction
```

Reasoning and queries (`pip install -r requirements.txt`):

```sh
sh engine/fetch_ddl.sh                                    # third-party DDL engine, fetched and patched
python tools/run_cases.py                                 # 53 civil scenarios, 138 expected conclusions
python tools/run_criminal_cases.py                        # 30 criminal scenarios, 69 expected conclusions
python tools/run_cases.py reasoning/cases/q526.json -v    # item 526 with derivations
python tools/cq_eval.py                                   # competency questions (12 of 13 pass)
python studies/retrieval/or_flattening.py                 # 114 of 537 disjunctive rules lose "or"
```

`validate` checks integrity, not XSD validity or legal correctness; `resources/schema/` holds the OASIS schemas.
