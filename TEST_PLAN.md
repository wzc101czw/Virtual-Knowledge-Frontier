# VKF v0.2.0 测试计划

执行 `python -m unittest discover -s tests -v` 运行自动化回归；
执行 `python examples/demo_consolidation.py --db .\demo-v2.db --vault .\DemoVault` 检验真实生成的 Obsidian 结构；
人工语义验收详见 `ACCEPTANCE_PLAN.md`。

应重点测试：schema v3→v4 无损迁移、Windows GBK、长文本偏移、候选去重保留来源、REVIEW 不自动变更正式知识、审核后状态一致性、同主题相反结论的误合并保护、API settings 不保存密钥、Obsidian 只读投影与冲突检查，以及 rerun 不重复调用模型。
