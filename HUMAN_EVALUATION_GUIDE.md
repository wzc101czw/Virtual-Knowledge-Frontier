# VKF v0.3.0 · 人类研究员提炼质量评估

> 新版最重要的成果不是卡片数量，而是研究者能否通过一份结构化的研究空间恢复思路、辨认自己的原创想法，并继续开展研究。

## 1. 人类粒度评价不是模型自评

每一个 `research map` 对应一个**待审核的研究结构版本**。研究员先评价提炼是否：

- `too_fragmented`：有太多平级观点，主构想/子想法没有归纳成整体；
- `too_coarse`：多个不同路径被压成一个模糊大主题；
- `balanced`：信息层级和展开深度符合研究者自然的思考单位；
- `missing_important`：关键内容缺失，尤其是用户提出的原创想法、技术问题、引用研究或实验路径。

同时可以给三个维度打 **1–5 分**：

| 维度 | 1 分 | 3 分 | 5 分 |
|---|---|---|---|
| `structure_score` | 主 Idea、Sub-idea、研究资料完全混杂 | 有主线但层级有明显瑕疵 | 与研究者的研究结构高度一致 |
| `question_coverage_score` | 大量关键技术问题漏提 | 部分问题遗漏或笼统 | 关键问题及其具体研究语境都被保留 |
| `provenance_score` | AI 提议误记为本人或引用失真 | 有少量来源归属偏差 | 原创性、助手建议及外部资料均清楚且有来源 |

每条重要观点还应能定位到原始聊天的 `message_id`、`start_char` 和 `end_char`。这里的 `input_coverage=1` 只证明原文被完整送入映射过程，**不代表所有重要认知内容都被正确提炼**。

## 2. 实际反馈流程（PowerShell）

```powershell
$DB = "D:\VKFData\vkf.db"  # 替换为真实路径

# 仅提供可能的旧研究空间候选，绝不会自动合并
python -m vkf_storage --db $DB research suggest-spaces CONV_ID

# 完整映射研究结构，LLM 会将对话发送到已配置的提供商
python -m vkf_storage --db $DB research map CONV_ID --mode llm

# 查看并导出一个待审核研究结构
python -m vkf_storage --db $DB research map-show RMAP_ID
python -m vkf_storage --db $DB research map-export RMAP_ID "D:\VKFData\research-plan.json"

# 给出研究者的真实评估反馈，明确要合并的观点及遗漏的问题
python -m vkf_storage --db $DB research feedback RMAP_ID too_fragmented `
  --note "把研究架构的多个实现路线误切为平级 Idea" `
  --missing "动作 Token 与跨身体泛化" `
  --structure-score 2 --question-coverage-score 3 --provenance-score 5

# 手动编辑 plan.json 中的 contexts、views、role、parent_key、技术问题等
# 以下命令是修订提案，不会直接修改正式认知空间
python -m vkf_storage --db $DB research revise RMAP_ID "D:\VKFData\research-plan.json" --expected-revision 1

# 新版本重新评价
python -m vkf_storage --db $DB research feedback RMAP_ID balanced `
  --note "保留了完整架构与各子方案" --structure-score 5 `
  --question-coverage-score 5 --provenance-score 5

python -m vkf_storage --db $DB research feedback-summary

# 可选：导出只包含研究员反馈的 JSON 以便分享；请先检查有无私人内容
python -m vkf_storage --db $DB research feedback-export "D:\VKFData\vkf-human-feedback.json"
```

**为了清楚地表达具体改动**，还可创建一个 JSON 数组并使用 `--edits-file`：

```json
[
  {"action":"group","keys":["ctx-physical","ctx-action"],"comment":"都是同一个联合预训练架构下的路线"},
  {"action":"promote","keys":["view-user-core"],"comment":"应成为 Main Idea"},
  {"action":"add_question","keys":[],"comment":"遗漏动作 Token 和训练数据质量问题"}
]
```

当前这些结构性建议仅作为**人类标注保存**；它们不会未经用户确认就被模型自动学习或自动改写其他研究空间。

## 3. 正式确认研究结构

```powershell
python -m vkf_storage --db $DB research review-plan RMAP_ID
python -m vkf_storage --db $DB research review-apply RMAP_ID `
  --confirm "REVIEW_PLAN_TOKEN" --expected-revision 2 --reason "审阅并修正过结构"
python -m vkf_storage --db $DB research list
python -m vkf_storage --db $DB bridge export
```

`review-apply` **只确认研究空间的结构**，不证明所有内部 AI 假设是真实的，也不自动创建正式个人 Understanding。

## 4. 推荐验收方案

首先让研究员独立阅读原始对话并写一份简短“黄金纲要”，再看 VKF 生成的 Research Space。最重要的是**盲评：先写自己的纲要，不要先看模型卡片**，减少锚定效应。

建议至少覆盖：

- GC-01：具身智能预训练头脑风暴（总体架构 / SAGE-nano / Inverse Reasoning / Token / 数据 / 因果 / 迁移 / 实验）；
- GC-02：两场 Grothendieck Topos 研究对话（重复核心 / 新增应用 / 数学边界）；
- GC-03：不应合并的异质 AI 主题负例。

**第一阶段质量目标（不是本版已测成绩）：**

1. 100% 保留输入对话字符区间，不发生静默截断；
2. Golden Case 关键研究元素的人类标注召回率 100%；
3. 至少 80% 的人工评价为 `balanced`（正式统计前建议至少十场样本）；
4. `structure_score` 和 `question_coverage_score` 的人工平均分至少 4/5；
5. `provenance_score` 至少 4.5/5，任何严重原创性错认需单独记录；
6. 人类纠正后，**同一研究 Map 的下一版本评分应提高**；
7. 即便相似度很高，不能吞并用户认为独立重要的路线或问题。

评估报告须同时呈现：过碎率、过粗率、遗漏项排名、版本改善数量、研究员评分均值和结构级别的具体失败案例。小样本率不能被解读为跨研究领域的可靠总体性能。

## 5. 当前已知边界

- 启发式 Research Mapping 是**演示与无 API 骨架**，不能期待独立还原深层技术研究。请使用 `--mode llm` 并人工评价。
- v0.3 研究空间是独立层，旧 Candidate 和 Topic 不会自动升级；存在待整合的历史认知是预期状态。
- 研究空间候选发现是保守词汇匹配，尚未加入 Embedding / 混合检索。没有命中不是“全球新颖”的证明。
- `Synthesis` 只产生带来源的**研究提案**，`Compatibility` 的相容性结论没有数学层条件保证。
- Obsidian 中研究概览仍为 SQLite 受管的只读投影。应通过导出 JSON → 编辑 → 带确认令牌写回，而非直接改动生成的 Markdown。
