# 民法graph → LegalRuleML → Defeasible Deontic Logic

把 `source/民法graph.markdown`（约 43.8 万字、8355 个节点的民法笔记）转换成 **OASIS LegalRuleML Core 1.0**（compact 序列化），再按 Governatori 等人的 LegalRuleML→DDL 思路转换为 **Defeasible Deontic Logic 的 ASP 编码**，用 clingo 执行，并逐步给出推理解释。

```
民法graph.markdown ──graph_parse.py──▶ graph_nodes.json
        │                                   │
formal_rules.py（人工形式化）               ▼
        └──────────────graph2lrml.py──▶ civil_graph.lrml  ✔ 官方 XSD 校验通过
                                            │
                                     lrml2ddl.py（读 XML）
                                            ▼
                     civil_rules.lp ──clingo + DDL 引擎──▶ run_cases.py（cases.json，推理链）
```

## 一键运行

```sh
python3 graph2lrml.py          # 生成 civil_graph.lrml + civil_graph_index.json，做原文核对、锚点检查、XSD 校验
python3 lrml2ddl.py            # civil_graph.lrml → civil_rules.lp
./fetch_ddl.sh                 # 拉取 DDL 引擎（固定版本 + 补丁），只需一次
pip install clingo
python3 run_cases.py           # 53 个案例 / 138 条预期结论
python3 run_cases.py suc-2 -v  # 单个案例 + 推理链
```

## 两层结构

| 层 | 内容 | 来源 | 规模 |
|---|---|---|---|
| 结构层 | 图的每个节点 → 嵌套 `lrml:Statements` / `lrml:FactualStatement`，原文、Priority、考点、例外信号写在 `lrml:Comment` | 自动，无损 | 8355 节点 |
| | 笔记引用的法条 → `lrml:LegalSource`（《民法典》条文原文逐字截取；其他法律只记名称和条号），用 `Association` 连接节点 | 自动 | 342 个法源 |
| | 分类树 → `isA` 构成性规则（只保留父子概念中心词一致的边，如 留置权 ⊑ 担保物权） | 自动（权威 = `graph`） | 201 条 |
| 规则层 | Constitutive / Prescriptive 规则（Obligation、Prohibition、Permission、Right），带 Naf 例外、强否定、析取、`Override` | 人工（`formal_rules.py`） | 176 条、47 条显式优先关系 |

规则层的每条规则都挂在笔记中对应的节点**之下**（例如 `c399` 挂在“禁止抵押的财产”节点），因此在 LegalRuleML 里可以从笔记节点直接找到形式化规则，反过来也可以。每条规则通过 `Association` 关联到：条/款级法源（`appliesSource`）、权威（`npc` 条文明文 / `doctrine` 学理 / `spc` 司法解释）、强度、施行时间（2021-01-01）。

规则层覆盖的 10 个模块：民事行为能力与法律行为效力、可撤销与除斥期间、诉讼时效、抵押与最高额抵押（含流押、流质）、留置、地役权、合同（要约撤销、三大抗辩权、违约金与定金、债权转让与债务承担、买卖风险负担、买卖不破租赁、承租人优先购买权）、夫妻财产与债务、继承、特殊侵权。
代理与善意取得已有 `../agency_ch7.lrml`、`../property_gf.lrml`，这里没有重复。

## LegalRuleML → DDL 的映射（lrml2ddl.py）

| LegalRuleML | DDL（Governatori ASP 实现） |
|---|---|
| ConstitutiveStatement | `constitutiveRule(L, h)` |
| Obligation p / Prohibition p | `prescriptiveRule(L, p)` / `prescriptiveRule(L, non(p))` |
| Permission p | `permissiveRule(L, p)` |
| Right p | `constitutiveRule(L, p)`（权利作为可以被例外否定的法律地位） |
| `ruleml:Neg` / `ruleml:Or` | `non(·)` / 每个析取支生成一条规则 |
| `ruleml:Naf q`（“除非 q”） | 生成例外规则 `L'`：体 ∧ q ⇒ 对立结论，并加 `superior(L', L)`；其他推出同一结论的规则一律优先于 `L'`。这样 Naf 只阻断宿主规则，本身不证立 ¬h |
| `Override(over, under)` | `superior/2` |
| 变量 | 不预先展开：生成带变量的 ASP 规则，由 clingo 在 `cand/1`（可能成立的原子）上实例化 |

DDL 的 ASP 实现目前只支持可废止规则，所以 Strict 规则也按可废止规则处理。
如果某条规则的体里含有它所否定的结论（例如“有留置权 ∧ 约定不得留置 ⇒ ¬留置权”），DDL 中会构成循环。转换器遇到这种规则会直接报错，此时应改用底层事实来写。

## 验证结果

- **XSD**：`civil_graph.lrml` 通过 OASIS LegalRuleML 1.0 compact schema 校验（`schema/`，已改为本地 import）。
- **原文**：规则层引用的 122 个条/款全部由程序从《民法典》逐字截取。
- **案例**：53 个案例、138 条预期结论全部通过，包括跨模块的多跳链，例如：
  - `suc-2`：17 岁立遗嘱 → 限制民事行为能力（第19条）→ 遗嘱无效（第1143条）→ 法定继承（第1123条）→ 第一顺序继承（第1127条）
  - `tort-2`：7 岁 → 无民事行为能力（第20条）→ 第三人侵权（第1201条）→ 幼儿园只承担补充责任，第1199条的过错推定被排除
  - `suc-1`：父亲故意杀害被继承人而丧失继承权，这个例外只排除父亲本人，不影响配偶继承；兄弟（第二顺序）因此不继承

## 局限

- 规则层覆盖了 321 个“例外信号”节点（但是/除外/不得对抗……）中的 45 个，约 14%（按节点所在子树统计）。各编的覆盖情况：继承 7/10、婚姻家庭 7/20、物权 12/68、总则 5/60、合同 9/116、侵权 5/17，人格权与知识产权为 0。`civil_graph_index.json` 的 `exception_candidates` 列出了全部例外节点，以及每个节点已由哪些规则形式化，可以作为后续形式化的工作清单（人工完成，或用 LLM 按 Horner et al. 2025 的流程批量抽取后再人工抽检）。
- 自动抽取的 `isA` 边有少量噪声（如“合伙合同 ⊑ 不定期合同”）。这些边的权威标为 `graph`，不应和条文规则同等对待。
- 期间、金额一类的计算没有建模（例如“已满三年”是作为事实输入的）。这部分更适合交给 SMT（Z3）处理。
- 推理链中，每个结论只展示一条实际胜出的规则实例。

## 发现的问题

**笔记引文与现行法典原文不一致（8 处）**，大多是旧法措辞：

| 节点 | 笔记行号 | 条文 | 差异 |
|---|---|---|---|
| g0179 | 198 | 第1260条 | 文中混入“15” |
| g2550 | 2840 | 第319条 | “参照”→ 现行为“参照适用” |
| g4099 | 4550 | 第593条 | “因第三人原因”→ 现行为“因第三人的原因” |
| g4750 | 5261 | 第823条 | “损害赔偿责任”→ 现行为“赔偿责任” |
| g5414 | 5976 | **第736条** | **条号错误**：该句是第737条 |
| g6026/g6032/g6039 | 6652/6660/6667 | 第986–988条 | “获得的利益”→ 现行为“取得的利益” |

**上游 DDL 引擎**：`Deontic/deontic.asp` 第33–36行在 clingo 5.8 下报 unsafe variables。`ddl_deontic_unsafe_fix.patch` 按该处注释的本意修正。由于上游仓库未声明许可证，引擎不随项目分发，由 `fetch_ddl.sh` 在本地拉取。

**`../check_alignment.cn2int` 不处理“千”**，导致 `../build_property.py` 的 `load_code()` 对第1000条以后的条文解析错误（例如第一千零六十二条被当成第62条）。目前 `build_property.py` 只用到第641条以内的条文，所以没有实际影响。本目录的 `civil_code.py` 是修正后的独立实现。

## 文件

| 文件 | 说明 |
|---|---|
| `graph_parse.py` | markdown → 节点树（Priority、考点、引用、例外信号、概念名） |
| `civil_code.py` | 《民法典》条/款加载，支持 1–1260 条 |
| `formal_rules.py` | 人工形式化的规则层、优先关系、谓词中文释义 |
| `graph2lrml.py` | 生成 `civil_graph.lrml` 与 `civil_graph_index.json`，并做各项检查 |
| `lrml2ddl.py` | LegalRuleML（XML）→ DDL/ASP |
| `run_cases.py`、`cases.json` | 案例执行、核对与推理链 |
| `demo_lego.py` | 接入 LEGO 的单题演示：按 LEGO 检索到的条号选规则模块 → LLM 抽事实 → 引擎推理 → 结论附到 PFC-v3 提示后作答（`--no-llm --facts "..."` 只跑符号部分） |
| `schema/` | OASIS LegalRuleML 1.0 XSD（本地化 import） |
| `fetch_ddl.sh`、`ddl_deontic_unsafe_fix.patch` | DDL 引擎获取与补丁 |
