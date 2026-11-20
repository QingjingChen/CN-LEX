# 最新民法典审核草稿的关系检索

`export_review_relations.py` 只读 `~/codebook/LexReAct` 中生成审核表的结构化草稿，复用 `build_review_all.all_rules/load_drafts/draft_rule`，采用与审核表一致的版本优先级与 DeepSeek 编号后缀。不会修改桌面工作簿、外部仓库或旧实验结果。它不会读取专家在工作簿中后加的批注或结论；后续审核回写需要单独设计。

导出过程的中间文件 `data/review_relations.json` 包含规则内容、规则所属行、模型来源、风险提示、草稿文件 SHA256、规则到法条映射，以及：

- `override`：源数据明确声明的优先关系，方向为优先规则 → 被覆盖规则；同一条文内的关系保留，但不制造法条自环。
- `depends_candidate / exception_candidate / negative_condition_candidate`：复现审核表的谓词名称匹配。这只是结构候选，没有证明参数可统一、正负极性一致、或 OR 分支必须成立。
- `text_references`：按审核表的文本匹配规则提取引致用语；能确定具体条号的加入检索，涉及编、前款、前条等未解析范围的保留为 `unresolved_scope`。
- `unresolved_overrides`：目标规则缺失的记录单独保留，不加入图，也不猜测目标。
- `draft_annotations`：草稿中自然语言的优先、除外和区分说明原样保留。没有结构化端点的自由文本只作注释，不凭空补成关系边。

**所有新关系均标 `pending_expert_review`。来源声明 override 也不等于专家已经认可。**

```sh
# 从 LexGo 仓库根目录执行；无需 API。
python legalruleml/cn_lrml_paper/experiments/export_review_relations.py
OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python legalruleml/cn_lrml_paper/experiments/civil_review_retrieval.py
~/.venvs/lcr_jurex/bin/python legalruleml/cn_lrml_paper/experiments/test_review_relations.py
```

`civil_review_retrieval.py` 比较 Dense、旧关系、新 override、新全部关系、新旧合并。固定编码器、原文表示、Top20 候选和 Top5 种子，分别报告候选内重排和邻居扩展。只在原有 76 题开发集上选择关系权重，报告原有 176 题测试集；测试集之前已用于其他研究，属于探索性验证。它不生成新的模型回答。

关系导出保留类型、方向、来源；检索适配器采用无向二值邻接，将关联法条加入候选或提升其检索分数，不执行 override 的法律后果。扩展池大小单独保存。不能将表现归因于已验证的法律推理。

现有完整重排序脚本也已接入可选参数，默认旧行为保持不变；新关系结果默认写入独立文件：

```sh
OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python legalruleml/cn_lrml_paper/experiments/civil_rerank.py \
  --review-relations legalruleml/cn_lrml_paper/experiments/data/review_relations.json \
  --output-prefix civil_rerank_review
```

加 `--review-overrides-only` 可以排除谓词匹配候选与文本引致，只用新导出的明确 override（仍合并旧关系）。

早期 JSON 路径结果：`results/civil_review_retrieval.json`；现在默认直接读取 LRML，详见 [LRML 接入说明](README_review_lrml.md)。完整层级/要件/规范重排也支持 LRML。这两套方法的特征和归一化方式不同，只能在各自控制条件内比较。

## 2026-11-20 验证结果

源草稿 602 行；合并旧规则后共 3,389 条规则。规则关系 7,828 条：明确声明的 override 556 条、名称匹配依赖候选 6,820 条、例外候选 324 条、负条件候选 128 条。另有 3 条无法解析目标的 override，未纳入图。文本引致匹配 198 条，其中 51 条定位到具体条号，其余只保留范围说明。

去除同条文自环和重复映射后，新 override 对应 143 对条文，全部新关系对应 2,636 对，新旧合并 2,902 对。规则边数量与法条边数量并不相同。

| 控制实验（176 测试题） | Recall@10 | NDCG@10 |
|---|---:|---:|
| Dense 原文 | 0.5346 | 0.3900 |
| 旧关系，Top20 内重排 | 0.5374 | 0.4056 |
| 新旧合并，Top20 内重排 | 0.5469 | 0.4078 |
| 旧关系，邻居扩展 | 0.5431 | 0.4087 |
| 新旧合并，邻居扩展 | 0.5469 | 0.4030 |

合并关系相对旧关系的 Top20 重排增量不显著：Recall@10 p=0.4313、NDCG@10 p=0.7809。仅新 override 的最优开发权重为 0。不能宣称新关系已显著优于旧关系。

现有完整 AKN+Element+Norm 管线的旧结果为 Recall@10 0.5539、NDCG@10 0.4038；接入后为 0.5516、0.4119。这是另一套特征/归一化配置，只作对应管线内的描述性比较，不借用上表的配对 p 值。BM25、Dense、AKN-only、Element-only 等不依赖规范关系的结果与原文件一致。

已完成源映射/状态/端点检查，以及类型过滤、双向检索邻接、无自环、无越界条文等回归测试。未修改桌面审核表；未调用收费 API；本次复用了已有 BGE 向量缓存。
