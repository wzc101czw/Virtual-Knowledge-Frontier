# v0.3.3 — Reasoning-channel-aware JSON Recovery

- v0.3.2 的 `reasoning_tag` 故障：现在仅剥离完全闭合的前缀 `<think>` / `<analysis>`，且只解析其后的独立完整 JSON；不能把模型推理中的 JSON 视作最终内容。
- 兼容独立 `reasoning_content` 和内容数组的显式推理段；只处理最终文本。
- 更精确的隐私安全诊断：`reasoning_prefix`、`final_shape`、`separate_reasoning`。
- 新增可选 `VKF_CHAT_REASONING_EFFORT=low`（以及其他官方枚举值），仅适用于支持该参数的兼容服务；未设置时绝不发送。
- 默认输出配置下的 v0.3.2 Research Mapping 检查点哈希保持兼容；显式更换推理强度则产生新的配置指纹。
- Schema 维持 v8；没有自动认知审批、没有数据库重建要求。
- 支持研究员可控恢复、严格不从推理文字中提取候选。
- 新增 16 个专用回归测试，附 [REASONING_OUTPUT_RECOVERY_GUIDE.md](REASONING_OUTPUT_RECOVERY_GUIDE.md)。
- `gpt-6-astra` 兼容端点上的真实行为需由用户自行实测；不能把离线测试视为真实 API 验证。

---

# v0.3.2 — JSON Diagnostics & Targeted Fragment Recovery

- 诊断 `HTTP 200` 但 Assistant `message.content` 不合法 JSON 的情形：在错误中给出 `content_shape`、请求的 JSON Mode 和服务商报告的 token 用量是否高于请求预算；默认不存储私人模型回复。
- 可选 `VKF_CHAT_DEBUG_DIR` 显式保存失败的 Assistant 回复到指定本机目录（不含输入 Prompt、API Key；可能包含私人认知资料，请勿分享未脱敏内容）。
- 新增 `research map --split-fragment N`：直接将已知失败的单个分块细分后重试，不重做成功的完整分块；`--split-on-json-error` 为遇到不合法 JSON 时的显式、单层自动拆分选项。
- 成功子分块利用现有 SQLite Schema v8 检查点持久化，下一次运行自动恢复；原文消息 ID、绝对字符范围不变，跨子分块结果经过完整原文证据校验。
- 模型请求严格以原有分块 Prompt 进行，保持 v0.3.1 旧成功检查点可复用；改用不同 JSON Mode/Token 配置仍会导致按签名失效，这是安全设计。
- 所有额外请求均需要用户显式开启功能；保持 v0.3.1 的网络超时不自动重发、严格解析、人工审核原则。
- **数据库 Schema 不变（v8）；不是完整的真实模型兼容性验证。**

详见 [RESEARCH_JSON_RECOVERY_GUIDE.md](RESEARCH_JSON_RECOVERY_GUIDE.md)。

---

# v0.3.1 — Resumable Research Mapping + Timeout Diagnostics

- 将研究映射任务的超时独立配置为 `research_timeout`（默认 300 秒），可用 `config set research-timeout` 持久修改或 `research map --timeout` 单次覆盖；不改变普通提炼的 60 秒默认值。
- 增加可配置的研究分块长度 `research_chunk_chars`（默认 13000 字符，可降低为 6500 等）以缓解服务商固定请求时限下的单次模型负载。
- 在 SQLite Schema v8 加入每分块、完整证据校验后的研究地图检查点；失败重试时根据完整请求签名安全复用成功的分块及必要的全局汇总，完成后自动清理。
- 错误报告增加 Connect/Header 与 Response Body 阶段、超时秒数、耗时，以及 Research Map 失败片段序号；不输出原始模型文本或 API Key。
- 新增 `research map-progress` 和 `research map --progress / --restart`，用于可见性与安全回退。
- 保留网络超时默认不自动重试，避免服务端已计费请求被静默重复调用。
- 调整生命周期删除逻辑，预览、备份与清理均覆盖未完成的 Research Map 检查点。
- 改正 `Storage.__init__` 中旧 Schema 检测时错误尝试迁移而引用不存在的局部变量的问题：迁移必须通过显式 `init` 完成。
- 没有修改原有认知数据模型与人工审核语义；仍需真实服务端性能和人类研究员的认知质量测试。

详见 [TIMEOUT_RECOVERY_GUIDE.md](TIMEOUT_RECOVERY_GUIDE.md)。

---

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
