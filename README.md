# CN-Onto · CLeXML

中文民法、刑法规则的 LegalRuleML 审核版资源。**仓库直接包含两份完整 LRML**，可克隆后读取，无需另找本机草稿、题库或模型。

| 资源 | 审核草稿行 | 合并后的规则 | 标准 Override |
|---|---:|---:|---:|
| [民法 civil_review.lrml](resources/civil_review.lrml) | 602 | **3,389** | 556 |
| [刑法 criminal_review.lrml](resources/criminal_review.lrml) | 467 | **2,875** | 431 |

这里的“完整”指当前审核草稿与既有规则合并后的完整导出，不代表穷尽民法典或刑法的所有法律规则。全部规则与新关系保留 `pending_expert_review` 状态。

## 使用

仅需 Python 3.9+ 标准库，无需安装依赖、下载模型或配置 API。

```sh
git clone https://github.com/QingjingChen/CN-Onto.git
cd CN-Onto
python3 cn_onto.py stats
python3 cn_onto.py article 1199
python3 cn_onto.py article 18 --law criminal
python3 cn_onto.py validate
```

`article` 输出规则中文说明、原始 RuleML XML 和关联的有向 Override。默认只展示前5条规则，并显示该条文规则总数；`--limit 0` 展示全部。`--relations all` 还输出待审核的依赖、例外候选及文本引致。

导出全部规则，供自己的检索或推理程序读取：

```sh
python3 cn_onto.py export --law civil --output /tmp/civil_rules.jsonl
python3 cn_onto.py export --law criminal --output /tmp/criminal_rules.jsonl
```

输出文件必须尚不存在。每行包含规则标识、关联法条、出处元数据、中文说明和完整 `statement_xml`，不截取每条法条的规则数量。XML 中的谓词定义与 Prefix 等上下文仍以完整 LRML 文档为准。

## 内容与边界

- 条件、结论、AND/OR、否定及义务/权利等结构写在 RuleML 规则中；规则通过 LegalSource / Association 关联法条。
- 刑法既有规则 `k-minor-conv` 的法条映射为空，原样保留并列入manifest；其余规则均有映射。校验会检查这一已知缺项，不自动补造法源。
- 优先关系使用标准 `Override(over, under)`，保留方向。556/431是规则关系数，不是不同法条对数。
- 依赖、例外等名称匹配候选及来源信息使用 `Comment` 中的 `CNLR_REVIEW_META:` JSON。它们是应用元数据，不能当作已经验证的可执行法律依赖。
- `validate` 检查文件哈希、规则数量、来源映射、XML引用、关系端点和Override方向；不执行XSD验证或证明法律内容正确。
- 当前入口负责读、查、导出与完整性检查，不执行案件推理，也不复现此前基于旧要件文本的检索结果。

## 目录

```text
cn_onto.py                  统一读取与命令行入口
resources/
  civil_review.lrml         民法完整审核资源
  criminal_review.lrml      刑法完整审核资源
  manifest.json             规则数量、版本出处与 SHA256
tests/test_resources.py     完整性与查询回归测试
```

出处记录保留模型、源草稿哈希及审核状态；本机绝对路径统一替换为 `LexReAct/...` 相对出处标识，因此发布文件哈希与原始本地文件不同。规则、法源和关系未删减。资源版本及原文件哈希见 [manifest.json](resources/manifest.json)。

精简前的实验脚本与旧版部分人工规则见 [历史版本 fb530d1](https://github.com/QingjingChen/CN-Onto/tree/fb530d12e9877180f7ab39de713df53946663987)。题库、原始笔记、审核工作簿、向量缓存和第三方引擎不随此版本分发。此精简未新增许可证授权；使用第三方来源内容时仍需核对相应授权。
