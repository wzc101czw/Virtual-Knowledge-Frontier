## v0.2.3 — Provenance-aware Consolidation & Candidate Links

- SQLite Schema v5（旧数据库先备份）：新增 `candidate_links`、`consolidation_reviews.comparison_scope`、`effect`；历史已接受的 Review 以 `legacy_unknown` 标明作用未知。
- 去除同场对话来源带来的相似度人为加分；显式标注 same/cross/mixed/none/unknown 来源范围。
- 对 `Question → Idea` 等跨认知类型的 LLM `REFINES` 提议保守降级为 `RELATED`，避免把新追问误记成命题修订。
- `consolidate run --scope cross|within|all` 区分跨对话巩固和对话内部展开。新提议按 scope/算法签名保持幂等，作用已确定的旧 Review 不会自动重复执行。
- 人工接受 REFINES/RELATED 时，写入**待正式化**的 candidate_links，不再仅设置 Review 的 applied 标记；未批准的认知仍不进入正式图谱。
- Obsidian 的 Candidate、Topic、Consolidation 页面呈现审核过的临时关系、比较范围及实际写入效果；补齐 .base 写入异常路径定位。
- `consolidate links` 查看临时关系；NEW 审阅仍需另外批准 Candidate。
- 修复 Storage.__init__ 中意外残留的 v3 升级分支，使旧数据库必须通过显式 init 迁移。
- 未包含远程模型服务测试、不保证自动 SAME 或跨学科语义召回；当前检索仍基于词汇。

## v0.2.2 — Model comparison JSON reliability

- Fixes invalid JSON example embedded in the Cognitive Consolidation comparison prompt.
- Enlarges the default comparison completion budget from 500 to 2048 tokens, including reasoning.
- New `model-probe --task compare` uses the actual comparison prompt with synthetic content (no private Vault data).
- A single model response format failure is reported against one candidate instead of aborting the entire `consolidate run` batch.
- JSON parse errors now include safe line/column metadata; model content and API tokens are never printed.
- `VKF_CHAT_JSON_MODE=json_object` is now the default; set `VKF_CHAT_JSON_MODE=none` for providers that reject it.
- No database migration, no automatic consolidation or approval.

## v0.2.1 — Model API diagnostic hotfix

- Distinguishes transport, HTTP body, API schema, and model output JSON errors.
- Includes finish_reason, token usage, limited safe metadata; does not log raw completions.
- Adds small `model-probe` command and optional compatible request settings.
- No SQLite migration or Vault changes.

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
