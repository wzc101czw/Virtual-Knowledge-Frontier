# VKF v0.2.3 验收计划 / Provenance-aware Consolidation

## 数据准备与安全

把旧 `vkf.db`、Vault 和原始导出先复制到单独测试目录。只在副本上进行升级与再提炼；不要把用户的真实私密导出打包到公开代码仓库。

## A. 工程必须全部通过（Pass/Fail）

| ID | 测试 | 通过条件 |
|---|---|---|
| E01 | 旧 v4 → v5 迁移（并回归验证 v3 → v5） | 自动备份成功，旧数据不丢失，`doctor.ok=true` |
| E02 | 设置持久化 | Vault、模型、API Base 重启后仍正确；不能配置保存 API Key |
| E03 | Windows GBK | 中文 / Emoji UTF-8 笔记回写与单元测试全部通过 |
| E04 | 多消息完整性 | v0.2 LLM 提炼完成后每个原始字符被完整覆盖，`coverage=1.0` |
| E05 | 重复调用幂等 | 同一输入和配置重复运行，不额外创建等价提炼 Run 或比较 Review |
| E06 | 审核隔离 | 建议产生时正式知识和关系不变 |
| E07 | SAME 确认 | 等价候选多来源，原始对话保留，批准后只有一份正式认知对象 |
| E08 | 禁止误合并 | 同主题结论不同（尤其否定句）不能被规则自动标记 SAME |
| E09 | 理解防伪 | AI 提出的 Understanding 无显式 `--confirm-understanding` 不可批准 |
| E10 | Obsidian | 可以打开 Topics、Review Inbox，已手改的托管文件不会被静默覆盖 |
| E11 | 数据库事务 | 中途失败不留下半成品，版本、关系、外键正常 |
| E12 | 敏感数据 | API Key 仅进环境变量，不能出现在 SQLite/设置文件/生成的 Vault 里 |

## v0.2.3 必测的针对性用例（本轮日志）

**P01 · 对话内部的论证结构与跨对话来源不应混淆。**

- 在测试库中保留两场不同对话，每场产生至少两条思想；运行 `consolidate run --mode llm --scope within` 后，仅展示来源有交集的候选关系；运行 `--scope cross` 后，不把单场对话的 7 个观点当作跨对话知识巩固证据。
- **验收：** 所有建议都能看到 `comparison_scope`；选出有确定来源的案例人工核对，**范围标注准确率 100%**。无法确认来源的标为 unknown，不能冒称 cross。

**P02 · 实际写入结果与审核状态一致。**

- 对一条 `REFINES` 和一条 `RELATED` 执行 `consolidate decide ... accept`。
- **验收：** `effect=provisional_relation`，`consolidate links` 可查到，并在 Obsidian 的 Candidate / Topic 页出现可点击链接；正式对象总数和关系总数保持不变。
- 对 `NEW` 执行 accept：`effect=acknowledged_only`，不得自动批准 Candidate。

**P03 · 重复命题与细化命题不能混为一谈。**

- 使用“最小充分生成”与“满足充分性的动态停止机制”等命题测试 REFINES；另外构造表达等价的不同措辞命题供 SAME 测试。
- **验收：** 同主题但具有新增机制的观点不得仅因词汇相似被规则标成 SAME。手动 SAME 经审核只归并来源、保留两个原始对话。

**P03b · Question 不应冒充对 Idea 的已验证细化。**

- 让模型对“最小充分生成” Idea 和“如何评估视觉留白？”Question 判断关系。
- **验收：** 即使模型输出 REFINES，系统也保守地给出 RELATED 并说明类型差异；人工仍能审查其价值。

**P04 · 旧版本审阅历史不被暗中重写。**

- 先手动备份 v4 数据库，再执行 `init`；确保生成 `pre-v5` 备份、通过 `doctor`。
- **验收：** 老 Review 保留 ID 和 rationale；老的 applied 行 `effect=legacy_unknown`，新 Review 才有准确效果标签。已接受的建议不得被自动重放。

**P05 · 无匹配不是新知识证明。**

- 创建两条同义但词面差异很大的表达；在纯词汇检索中可能看不到目标。
- **验收：** 系统必须解释「当前检索范围无匹配」，不能声称已证明整个 Vault 中不存在重复；手工评估 Retrieval Recall@8，达标前不能声称完成认知巩固。

**P06 · 核心人工指标。**

- 在至少 20 个经人工核实的跨对话正负配对中，分别量化 `SAME` Precision、召回率以及 `NEW` 漏检。
- 起始目标：**误判 SAME 为不同命题的错误次数为零**；完整数据量达到原计划要求后再使用百分比指标；该目标目前尚未用真实 LLM 验证。

## B. 语义质量（人工标注后评估，非已有成绩）

建议至少人工挑选 30 组候选配对（其中至少 10 组为 SAME、10 组为主题相同但命题不同），并标注至少 20 个价值门槛样本。若样本有限，先完整报告混淆矩阵，谨慎使用百分比。

| 指标 | 建议起始目标 | 计算/说明 |
|---|---|---|
| Extraction Coverage | **100%** | 每个成功处理的 v0.2 LLM 输入字符覆盖率 |
| Retrieval Recall@8 | **≥90%** | 人工标记为 SAME 的目标是否出现在前 8 个候选中 |
| SAME Suggestion Precision | **≥95%** | 标注集合中建议 SAME 的真阳性比例；误合并成本高，优先 Precision |
| SAME Suggestion Recall | **≥75%** | 标注为 SAME 的样本中有多少获得正确的 SAME 建议 |
| False-SAME Proposal Rate | **≤5%** | 明确 NOT-SAME 的标注样本上错误建议 SAME 的比例 |
| Low-value Gate Precision | **≥90%** | 建议 DISCARD 的样本中确属低价值日志的比例 |
| Low-value Gate Recall | **≥70%** | 低价值日志有多少获得 DISCARD 建议 |
| Unique Insight Retention | **100%** | 第二次对话独有的观点/追问不能随 SAME 被吞掉，人工逐条核对 |
| Human Review Time | **比手动整理减少 ≥30%** | 同批对话，对照人工 PKM 工作流计时，不混淆熟悉程度 |
| Useful Cross-Domain Suggestion Rate | **≥50%** | 由人判定有价值、明确局限的跨领域启发比例 |

`same_precision`, `same_recall`, `retrieval_recall_at_8`, `false_same_proposal_rate`, `noise_precision` 和 `noise_recall` 可通过 `evaluate` 命令测算；Unique Insight、Cross-Domain Utility 与人工审核时间需要另行主观标注。

## C. 与真实使用直接对应的测试案例

**C01 — 范畴论 / Topos 重复讨论。**

1. 在测试 DB 导入两个与 Topos / Monad / 局部到整体相关的对话（保留原始两次会话）。
2. 使用 `pipeline run --all --extract llm --compare llm --limit 2`。
3. 查看 Review Inbox：应有共同核心观点的 SAME/REFINES/RELATED 建议；若完全 NEW，记录漏检。
4. 人工将相同命题归并到 canonical Candidate 或已有 Object；来源应覆盖两场对话。
5. 第二场关于 Research Kernel 的新约束和开放问题应继续独立存在。不得因为 Topic 相同而自动被 SAME。

**C02 — 长文本具身智能对话。**

1. 选择至少一条超过 13000 字符的 Assistant 消息所在会话。
2. 对它运行 v0.2 LLM 提炼，并执行 `coverage CONVERSATION_ID`。
3. 预期无缺口（coverage=1.0）；若模型调用未全部成功，必须显式报告未覆盖区间。

**C03 — 低价值交付记录。**

1. 对“中文 PDF 报告交付记录”创建或重新提炼候选。
2. 期望 `DISCARD` 审核建议，但不能在人工操作之前删除候选或对话。

**C04 — Understanding 来源与掌握状态。**

1. 让模型提议一条来自 AI 回答的 Understanding。
2. 未显式确认的 `candidate approve` 必须失败。
3. 用户确认后也应保持 provisional，除非另有用户 teach-back 证据。

**C05 — 跨领域联想。**

将“信息学题目比较的标注成本”与“实验设计中最大化信息收益”作为人工对照：要求给出相关/类比证据、适用范围、关键差异。v0.2 只生成可审阅的建议，不保证能从全部 Vault 自动找到跨领域关系。

**C06 — 同主题相反命题。**

为“应该长期保存 Agent Memory”和“不应该长期保存 Agent Memory”各创建一条候选；规则比较不能生成 SAME。人工使用 `evaluate` 标记 NOT-SAME，以评估 LLM 比较误判。

## D. 反馈格式

将 `consolidate list` 结果、`coverage` 输出、`evaluate` JSON 和 3–5 个典型错误案例（脱敏后）一并保存。反馈要区分：**没有检索到目标**、**模型比较失误**、**自动 Topic 过粗**、**用户审核过重**、**数据库或 Bridge Bug**。优先定位错误发生在哪个 Pipeline 阶段。
