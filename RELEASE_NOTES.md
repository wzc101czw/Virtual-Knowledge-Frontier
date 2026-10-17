# v0.3.0 发布说明

新增受层论启发的研究空间、情境/局部观点、多来源综合与 Frontiers，并以研究员对粒度与结构的评价为首要验收标准；数据库迁移至 Schema v7。完整内容见 [RELEASE_NOTES_V030.md](RELEASE_NOTES_V030.md)。

---

## v0.2.4 — Model API resilience & lifecycle operations

- SQLite Schema v6：加入有来源信息的 `lifecycle_events` 和 Obsidian 托管文件归档清单 `lifecycle_retired_files`；原 v5 数据库迁移前自动备份。
- 四种预览式数据清理：`extraction`、`conversation`、`derived`、`all`；确认令牌绑定受影响 ID 与内容，真正应用前自动备份并在单事务内执行，Doctor 验证在提交前完成。
- 删除某场对话若会破坏已批准知识的来源则拒绝；相关 Review、Candidate Link、Topic 依赖同步处理。
- `lifecycle vault-prune` 只在用户确认后将指纹一致的旧托管笔记**移出 Vault**，保留旁路文件备份；人工编辑与符号链接一律拒绝自动移动。
- 对上游 429/500/502/503/504 提供有限退避重试；400/401/403 不重试，网络超时不盲目重试；对无效 JSON 再次请求一次更严格结构化输出。
- 可选 `VKF_CHAT_JSON_MODE=json_schema`、`model-probe --task extract`；仅适用于兼容 Chat Completions 的服务，第三方服务可能不支持。
- 不强制合并或批准认知，不改变 `SAME`/`REFINES` 的语义；保留 v0.2.3 的跨对话范围与临时候选关系。
- 本版没有调用真实 GPT6-Astra API，也不保证第三方服务完全遵守 JSON Mode；重试会带来额外 API 费用。

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
