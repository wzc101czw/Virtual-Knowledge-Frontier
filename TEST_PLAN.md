# v0.3.0 测试入口

`python -m unittest discover -s tests -v`。重点：`tests/test_research_v030.py`、`tests/test_research_llm_and_feedback.py`。测试来源区间完整性、原始对话不丢失、v6→v7 数据迁移、研究员反馈与版本、跨空间情境、多来源综合提案、Obsidian 安全覆盖、生命周期清理及模型接口的模拟结果。**实测 GPT6-Astra 和人类认知质量未包含在自动化测试中**。

---

# VKF v0.2.0 测试计划

执行 `python -m unittest discover -s tests -v` 运行自动化回归；
执行 `python examples/demo_consolidation.py --db .\demo-v2.db --vault .\DemoVault` 检验真实生成的 Obsidian 结构；
人工语义验收详见 `ACCEPTANCE_PLAN.md`。

应重点测试：schema v3→v4 无损迁移、Windows GBK、长文本偏移、候选去重保留来源、REVIEW 不自动变更正式知识、审核后状态一致性、同主题相反结论的误合并保护、API settings 不保存密钥、Obsidian 只读投影与冲突检查，以及 rerun 不重复调用模型。
