# Study II: rule-granular retrieval (Sect. 5)

Statute retrieval over the 1,260 Civil Code articles; numbers from a separate study in preparation (LEGO-Rule).
Encoder: Qwen3-Embedding-8B. Benchmarks: LawExamQA (723), LexRAG (1,641), PLawBench (114).

| Method | LawExamQA R@8 | N@10 | LexRAG R@8 | N@10 | PLawBench R@8 | N@10 |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 66.24 | 54.33 | 52.80 | 40.80 | 44.75 | 41.38 |
| LEGO (expert graph) | 71.04 | 56.19 | 53.34 | 39.88 | 48.01 | 42.57 |
| LEGO + rules as units | 74.40 | 59.34 | 55.07 | 41.94 | 49.80 | 44.46 |
| LEGO + sentences as units | 73.28 | 58.83 | 55.41 | 41.99 | 49.76 | 45.56 |

`verbalised_rules.jsonl` holds the 3,374 rule texts the retriever encodes. `python or_flattening.py` reproduces the
count of disjunctive rules whose verbalisation loses "or" (114 of 537).
