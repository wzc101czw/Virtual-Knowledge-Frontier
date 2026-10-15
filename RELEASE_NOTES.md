# v0.2.0 — Cognitive Consolidation

- Schema v4 迁移，自动备份已有 schema v3；新增无损分块溯源、Topic、Review、Candidate Attribution 与 Canonical Equivalence 表。
- `config set/show` 保存每数据库的 Vault、模型、API base、timeout 和默认处理模式；**不保存 API Key**。
- `pipeline run --all` 重提炼已导入的对话，旧版记录不被自动删除。
- 以字符偏移完整覆盖长消息，解决 v0.1.x 的长回复静默截断。
- 检索旧 Candidate 和 Knowledge，创建 SAME/REFINES/RELATED/CONTRADICTS/NEW/CROSS_DOMAIN/DISCARD 建议。
- 字面完全一致的 SAME 可以由规则发现；其他语义判断需要模型或人工审核。没有自动合并正式认知对象。
- 审核后的候选来源可以归并，且 canonical 正式批准后同步标记重复候选。
- Obsidian `VKF/01 - Consolidation.md`、`VKF/Consolidation/`、`VKF/Topics/` 与 `Consolidation Inbox.base`。
- `coverage` 和 `evaluate` 支持字符级完整性、人工标注的误合并/召回等度量。
- `candidate approve` 对 Understanding 新增显式用户确认要求。

## 仍需进一步研发

语义检索 Embeddings、CrossInsight 自动合成、持续式知识演化、自动版本冲突协商、Obsidian GUI 审核按钮、完整多模态对话导入。请不要把本版的主题聚合看作已经证明了认知层面的理解。
