# 民法与刑法审核规则正式序列化为 LegalRuleML

已生成独立、可重复导出的两份 OASIS LegalRuleML 1.0 compact 文档，不覆盖早期图谱：

| 文件 | 审核表草稿行 | 合并原有规则后的规则数 | `lrml:Override` | 不同条文间的无向 override 对 |
|---|---:|---:|---:|---:|
| `../lrml/civil_review.lrml` | 602 | 3,389 | 556 | 143 |
| `../lrml/criminal_review.lrml` | 467 | 2,875 | 431 | 7 |

规则数包含原有规则与按生成审核表时同一优先级选中的模型草稿。刑法多数优先关系发生在同一条文内部，不能把 431 个规则关系说成 431 对条文。生成阶段不修改审核工作簿或外部源仓库，不调用 LLM API。

## 在 LRML 中怎样记录

- 实际条件、结论、否定、析取与义务/权利等：`ConstitutiveStatement / PrescriptiveStatement` 下的 `ruleml:Rule`。
- 实际法律来源：`LegalSources / LegalSource`，`Association` 以 `appliesSource / toTarget` 绑定规则，保留条/款及刑法“第N条之M”的区别。
- 源草稿明确列出的优先关系：标准 `OverrideStatement / Override(over, under)`，保留方向。部分刑法源关系来自之前重启后的推断恢复，其来源风险提示随规则写入，不代表专家确认。
- 谓词名称匹配得到的依赖/例外/负条件候选：写入 **`FactualStatement` 的 `Comment` 应用元数据**，类型仍为 candidate，未伪装成标准可执行的 Override。刑法有 774,313 条依赖候选、484 条例外候选、1,000 条负条件候选，说明名称匹配非常宽泛，不能当作可靠法律依赖。相同来源与谓词的候选按目标列表分组压缩，读取时可无损还原。
- 文本引致、自然语言优先/例外/区分注释，以及缺少目标的关系，也放在文档内的元数据中；范围未解析或目标缺失时不制造有效边。
- 规则所属审核行、模型、风险提示、草稿 SHA256 与 `pending_expert_review` 状态直接嵌入文档。不是旁边有一个 JSON 才能读。

元数据格式为 `lrml:Comment` 文本中的 `CNLR_REVIEW_META:` 加 JSON，字段为 `kind / record`。这是本项目的可移植应用约定，不是声称 OASIS 标准定义了 `depends_candidate`。普通 LRML 工具可读取规则及标准 Override；本项目读取器额外识别这些待审核注释。

民法 3 条原始 override 的目标规则缺失，保留在文档的 `unresolved_overrides` 记录中，未写成悬空 `Override`；刑法没有此类悬空记录。不自动猜补目标。

## 导出与读取

从 LexGo 仓库根目录执行：

```sh
# 生成两份 JSON 中间件，再序列化为两份 LRML，并执行 XSD / keyref 检查
python legalruleml/cn_lrml_paper/experiments/export_review_lrml.py

# 单独导出某一部法：追加 --law civil 或 --law criminal

# 直接从 LRML 查第1199条的 override 邻居，应得到1201
python3 legalruleml/cn_lrml_paper/experiments/review_lrml_reader.py \
  legalruleml/cn_lrml_paper/lrml/civil_review.lrml --article 1199 --overrides-only

# 刑法第18条的关系，可用同一读取器；条文之M使用例如17-1
python3 legalruleml/cn_lrml_paper/experiments/review_lrml_reader.py \
  legalruleml/cn_lrml_paper/lrml/criminal_review.lrml --article 18 --overrides-only
```

`review_lrml_reader.article_neighbours(path, types, valid_articles)` 是民刑通用检索接口。读者从 LRML 的真实法源 Association 重建规则→条文映射，并核对嵌入元数据；标准 Override 方向以 XML 的 `over / under` 为准，发现元数据方向不一致会报错。检索可以使用无向邻接找到关联条文，但这不表示法律上的优先方向是双向的。

现在 `civil_review_retrieval.py` 默认读取 `civil_review.lrml`。完整民法重排也已支持：

```sh
OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python \
  legalruleml/cn_lrml_paper/experiments/civil_rerank.py \
  --review-relations legalruleml/cn_lrml_paper/lrml/civil_review.lrml \
  --output-prefix civil_rerank_review_lrml
```

加 `--review-overrides-only` 只加入标准 Override，避免用全部宽泛的候选关系。刑法此次完成 LRML 导出和相同读取接口的验证，没有声称重新跑过刑法检索或 QA 基准。

## 验证证据

- `results/review_lrml_validation.json`：两份文档 XSD 通过、key/keyref/over/under 完整性通过、文件 SHA256。
- `test_review_lrml.py`：两部法全部规则的来源/状态/模型出处，以及全部关系的顺序无关摘要一致；第1199条→第1201条实际读取；篡改 Override 方向会触发错误。
- `results/review_lrml_reader_check.json`：民刑规则数、跨条优先关系数量及实例。
- `results/civil_review_lrml_retrieval.json`：直接读取 LRML 的民法控制实验；图规模、开发权重、所有指标/显著性及逐题排名与 JSON 路径一致。
- `results/civil_rerank_review_lrml_results.json`：现有完整重排管线直接读取 LRML 的结果，独立文件保存。

```sh
python legalruleml/cn_lrml_paper/experiments/test_review_lrml.py
~/.venvs/lcr_jurex/bin/python legalruleml/cn_lrml_paper/experiments/test_review_relations.py
```

XSD 通过代表序列化结构符合模式，不能证明规则内容法律上正确。所有模型草稿与新关系仍待专家审核；本次未将审核表后续人工改动自动回写，也没有替换原有四份图谱或自动扩大论文的实证结论。
