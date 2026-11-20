# CLeXML: LegalRuleML for Chinese criminal and civil legislation

Code for building and evaluating CLeXML, a LegalRuleML-based representation of the
PRC Criminal Law and Civil Code, anchored to Akoma Ntoso URIs.

This repository contains **code only**. Source notes, generated LegalRuleML files,
review workbooks, exam questions and third-party datasets are **not** included
(copyright / licence restrictions); see "Data" below for how to obtain them.

## Layout

| Path | Content |
|---|---|
| `legalruleml/civil_graph/` | civil expert map → two-layer LegalRuleML; hand-written rule layer (`formal_rules.py`); LegalRuleML → DDL/ASP (`lrml2ddl.py`); scenario tests (`run_cases.py`, `cases.json`) |
| `legalruleml/crim_graph/` | the same for the Criminal Law (`crim_rules.py`, `crim2lrml.py`, `criminal_code.py`) |
| `legalruleml/cn_lrml_paper/build/` | JUREX-4E → four-element LegalRuleML (`jurex2lrml.py`), auto-generated engine tests (`test_jurex_rules.py`), LEGO concept cards → LegalRuleML (`cards2lrml.py`) |
| `legalruleml/cn_lrml_paper/experiments/` | RDF export and SPARQL competency questions; review-stage LegalRuleML export/reader; retrieval experiments (typed, directed normative relations: `civil_semantic.py`); retrieve → CLeXML subgraph → reasoning QA (`clexml_reason_qa.py`); similar-charge disambiguation (`scd_clexml.py`); CAIL2018 charge representation study |
| `legalruleml/cn_lrml_paper/minimal_retrieval/` | **minimal civil retrieval experiment** (numpy only, < 1 s): reads the CLeXML LegalRuleML semantic web directly, two-stage retrieval with typed and directed normative relations, step-by-step NDCG explanation (`--explain`); `README_zh.md` walks through two examples. Its `data/` bundle (questions, articles, BGE-m3 vectors, `civil_review.lrml`) is produced by `experiments/export_minimal_bundle.py` and is not distributed |
| `legalruleml/lcr_jurex/` | JUREX-4E similar-case retrieval setting (LeCaRDv2 / GEAR), data fetch script |

## Data (not distributed)

- Civil Code / Criminal Law text: public statutes; `crim_graph/criminal_code.py --fetch` rebuilds the Criminal Law text.
- OASIS LegalRuleML 1.0 XSDs: download from docs.oasis-open.org into `civil_graph/schema/`.
- DDL engine: `civil_graph/fetch_ddl.sh` (pinned revision + one-line patch).
- JUREX-4E, LeCaRDv2/GEAR, CAIL2018: `lcr_jurex/fetch_data.sh`.
- GCI similar-charge data: `data/data.zip` of https://github.com/xxxiaol/GCI → `lcr_jurex/data/gci/data.json`.
- Expert maps, LEGO cards, LexGo questions, bar-exam questions and review workbooks: available from the authors on request.

## Running (examples)

```sh
pip install -r legalruleml/cn_lrml_paper/requirements-retrieval.txt lxml rdflib clingo
python legalruleml/civil_graph/lrml2ddl.py && python legalruleml/civil_graph/run_cases.py
python legalruleml/cn_lrml_paper/build/jurex2lrml.py
python legalruleml/cn_lrml_paper/experiments/civil_semantic.py
python legalruleml/cn_lrml_paper/minimal_retrieval/minimal_retrieval.py --explain 529
python legalruleml/cn_lrml_paper/experiments/clexml_reason_qa.py --law civil --offset 40
```

LLM-based experiments read `LLM_API_KEY` / `LLM_API_URL` from a `.env` file (never committed).
All model-drafted rules and relations are marked `pending_expert_review`; XSD validity and
engine tests check structure, not legal correctness.
