# JUREX-4E 类案检索（LCR）+ 刑法 LegalRuleML

问题：在 JUREX-4E 的 LCR 设置（论文第 8 节）下，刑法 LegalRuleML 图谱（`../crim_graph`）提供的条件知识能否改进检索？

## 数据

- 候选池：LeCaRDv2 的 1390 候选子集，来自 GEAR（Qin et al. 2024，github.com/E-qin/GEAR，`master` 分支）。JUREX-4E 沿用了这个子集。
- 测试查询：`test_qids.json` 有 92 项，但只有 **54 个不同查询**（有重复）。论文按 54 个唯一查询评测：BGE 基线的 R@1/5/10/20/30 与论文表 4 **完全一致**，NDCG@10 为 0.4745（论文 0.4737）。
- 专家四要件：JUREX 仓库 `data/flattened_jurex4e.json`。
- 指标：论文表 4 中的 “MRR” 实际是**所有相关文档倒数排名的平均**（复现值 0.1916，论文 0.1926），记为 `MRR_paper`。标准 MRR（首个相关文档）单独列出。

```sh
sh fetch_data.sh                                   # 下载数据（MIT）
python3 lrml_charge_kb.py                          # crim_graph → data/lrml_kb.json（70 个罪名：四要件 + 条件清单）
python3 llm_pipeline.py predict                    # 查询罪名预测（qwen-plus）
python3 llm_pipeline.py fet --guide expert      --model qwen-plus
python3 llm_pipeline.py fet --guide expert_cond --model qwen-plus
python3 build_runs.py texts --guide expert; python3 build_runs.py texts --guide expert_cond
PY=~/.venvs/lcr_jurex/bin/python                   # torch + sentence-transformers
$PY dense_retrieve.py --field fact -o runs/bge_fact.json
$PY dense_retrieve.py --texts cache/texts_expert_q.json cache/texts_expert_c.json -o runs/bge_fet_expert.json
$PY dense_retrieve.py --texts cache/texts_expert_cond_q.json cache/texts_expert_cond_c.json -o runs/bge_fet_expert_cond.json
$PY build_runs.py fuse                             # 结果表 + 配对随机化检验 → runs/summary.json
```

## 知识表示的关系

JUREX 专家四要件与刑法导图的“构成要件”**同源**：二者罪名集合一致（GEAR 的 100 个罪名中都覆盖 69 个，导图另多 1 个）；19 个罪名的文本几乎相同（例如诈骗罪“比如假毒品……调虎离山不算诈骗”）；整体相似度中位数为 0.61。所以“用 LRML 四要件替换 Expert-FET”基本等于用同一份文本，没有比较意义。LRML 真正多出来的是**条件结构**：

- 法定情节（法条枚举项）
- 罪与非罪
- 此罪与彼罪 / 转化

每条都有节点编号，对应 `crim_graph.lrml` 中的 Statement key。实验检验的就是这部分。

## 结果（54 个查询，qwen-plus，BGE-m3）

| 方法 | NDCG@10 | NDCG@30 | R@10 | R@30 | MRR_paper |
|---|---|---|---|---|---|
| BGE(fact) | 0.4745 | 0.5945 | 0.4298 | 0.7394 | 0.1916 |
| BGE+FET(Expert) — 复现 JUREX | **0.5176** | 0.6458 | **0.4817** | 0.8063 | 0.2139 |
| BGE+FET(Expert + LRML 条件进 prompt) | 0.5006 | 0.6244 | 0.4634 | 0.7753 | 0.2032 |
| BGE+FET(Expert) + 0.05·S_charge | 0.5059 | 0.6408 | 0.4524 | 0.7986 | 0.2158 |
| BGE+FET(Expert) + 0.05·S_rule | 0.5093 | **0.6517** | 0.4438 | **0.8117** | **0.2201** |
| BGE+FET(Expert) + 0.1·S_rule | 0.4819 | 0.6186 | 0.4303 | 0.7803 | 0.2072 |

论文中的对应结果：BGE+FET(Expert, Qwen2.5-72b) NDCG@10 0.5295、MRR 0.2206；GPT-4o 版本为 0.5211 / 0.2155。

## 结论

1. **复现成功**：专家四要件把 NDCG@10 从 0.4745 提升到 0.5176，与论文一致。
2. **把 LRML 条件清单加进 FET prompt 没有帮助**：NDCG@10 下降 0.017（p=0.12），MRR_paper 下降 0.011（p=0.017）。条件清单让 FET 文本变得更长、更偏重理论表述，冲淡了案情细节。
3. **S_rule 优于只匹配罪名的 S_charge**：λ=0.1 时 MRR_paper +0.015（p=0.08），NDCG@10 +0.009（不显著）。也就是说，“满足了哪些条件”在罪名之外提供了一点额外信号。
4. 但**加上符号项后，整体并不比 JUREX 原方法好**：λ≥0.1 时显著下降。λ=0.05 时 NDCG@30、R@30 和 MRR_paper 略高，NDCG@10、R@10 下降。而且 λ 是事后看测试集挑的，只能算探索性结果。原因主要是尺度：融合后余弦分数的跨候选差异很小，Jaccard 的取值范围是 0–1，λ 稍大就会让罪名一致压过事实相似。

## 局限

- 只有 54 个查询，统计功效很低。
- 用的是 qwen-plus 而不是 Qwen2.5-72b（DashScope 账户无权限）。
- 内容审核拦截了 1 个查询的罪名预测和 1 个候选的 FET，这两处空缺在各条件下相同。
- 图谱中“罪与非罪”节点大多写成“成立本罪要求……”，语义上并不是例外，所以 LLM 标注的“满足”多为门槛条件。
- 可执行规则层（93 条）只覆盖约 14 个罪名，本实验没有用到 clingo 推理。

## 下一步

- 用训练查询（599 个非测试查询）调 λ 和尺度（例如 rank 融合 / RRF），再在测试集上报告。
- 把 S_rule 限定在罪名一致的候选上做重排序，只比较条件向量。
- 把“罪与非罪”节点区分为门槛条件和真正的例外，并在 LRML 中显式标注。
