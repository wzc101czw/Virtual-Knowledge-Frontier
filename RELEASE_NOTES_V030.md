# VKF v0.3.0 · Contextual Research Space

**基线** v0.2.4 / SQLite v6 → **v0.3.0** / SQLite v7

## 此版本的新能力

- 研究空间级的整体优先组织：ResearchSpace、ResearchContext、ContextualView、ResearchReference；保留主 Idea / Sub-idea、来源归属、实验/技术问题。
- 无截断分块 Research Mapping 和跨分块整体归组。保留局部重要观点及证据来源，不再限制每块最多提炼 8 张卡片。
- `--mode llm` 使用原有模型设置和模型错误容错；`model-probe --task research` 仅用合成对话测试真实 Research Mapping Prompt。
- 为研究空间更新提供提案、人工编辑、版本控制、确认令牌与审阅提交；不覆盖旧 Candidate 和正式知识。
- Compatibility Assessment / Synthesis Proposal / Frontier Obstruction：记录不同情境的映射、需要的证据、未解缺口；严格保留未审核状态。
- 研究员可提供粒度判定、明确遗漏问题及 1–5 分的结构/问题覆盖/来源归属评分。支持版本修订前后的汇总与脱敏自查导出（笔记本身可能包含私有意见，分享前请审核）。
- Obsidian `VKF/02 - Research Spaces.md`、`VKF/Research Overview.base` 和每个已接受 Space 一份研究概览，抑制文件数量增长。
- v0.2.4 → v0.3.0 自动备份迁移和生命周期保护。

## 不在此版本范围内

不实现严格数学 Grothendieck Topos / sheaf；无 Embedding 或全局 semantic retrieval；不自动合并研究空间；不自动承认 Synthesis 为已掌握 Understanding；不提供 Obsidian 原生 GUI 审批；不做联网引用核验。

## 实验与验证

运行 `python -m unittest discover -s tests -v`；使用 `research map` 和 `research feedback` 在熟悉的真实研究对话中测试。自动化通过只代表工程正确性，不代表人类认知质量已经达标。
