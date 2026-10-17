# VKF v0.3.1 — Contextual Research Space & Timeout Recovery

**核心变化：由“从对话中生成更多平级卡片”，转向“先恢复研究整体，再审视局部观点的角色、证据、相容性及未解决问题”。**

- **v0.3.1 稳定性升级：** 研究映射默认 300 秒、验证后逐块存储检查点、重新运行时断点恢复。新数据库 Schema v8；详细见 [TIMEOUT_RECOVERY_GUIDE.md](TIMEOUT_RECOVERY_GUIDE.md)。
- **系统要求：** Python ≥3.10、SQLite 支持 STRICT / JSON / FTS5。运行时只有 Python 标准库；可选 Obsidian 和外部 Chat Completions API。
- **重要：** 正式版本的架构文档、生命周期、CLI 和回归测试见本包。`v0.3.0` 是可运行的研究空间原型，**不是**已经证实具有数学层性质、可靠科学综合或完成人类理解测量的系统。
- **关键验收：** 人类研究员实际判断整体/局部结构是否过碎、过粗、遗漏了哪类技术问题，并提供 1–5 分的真实性能评价，**不把 AI 自评当作成绩**。

## v0.3.0 快速开始（Windows PowerShell）

```powershell
$DB = "D:\VKFData\vkf.db"   # 替换为实际数据库路径
python -m vkf_storage --db $DB init   # v7->v8 创建 pre-v8 备份，较旧版本逐级迁移
python -m vkf_storage --db $DB doctor
python -m vkf_storage --db $DB config show

# 选择一场你自己熟悉的对话；先看看可能的历史研究空间
python -m vkf_storage --db $DB research suggest-spaces CONV_ID
# 生成待审核的整体研究地图（会调用 API，请确认自己的模型配置和费用）
python -m vkf_storage --db $DB config set research-timeout 300
python -m vkf_storage --db $DB research map CONV_ID --mode llm --progress
# 如中断：research map-progress CONV_ID；再次运行将复用已完成的局部块
python -m vkf_storage --db $DB research map-list

# 把结果导出为 JSON，研究员审阅并手动调整主构想、Sub-idea 和缺失问题
python -m vkf_storage --db $DB research map-export RMAP_ID "D:\VKFData\research-plan.json"
# 填写人类评价，而不是交给模型打分
python -m vkf_storage --db $DB research feedback RMAP_ID too_fragmented --note "子想法被切散了" --missing "动作 Token 表征"
python -m vkf_storage --db $DB research feedback-summary

# 如编辑了 JSON，再用 research revise RMAP_ID FILE --expected-revision 1
# 最后才能人工审阅确认研究空间（不会自动批准正式 Knowledge/Understanding）
python -m vkf_storage --db $DB research review-plan RMAP_ID
python -m vkf_storage --db $DB research review-apply RMAP_ID --confirm TOKEN --expected-revision 1 --reason "人工审核"
python -m vkf_storage --db $DB bridge export
```

Obsidian 将新增 `VKF/02 - Research Spaces.md` 与 `Research Overview.base`。一个正式研究空间对应一份可浏览的整体视图，生成笔记不会覆盖未同步的人工修改。原有 v0.2.4 Candidate / Consolidation 工作流仍可继续使用，但**不会自动转移到 Research Space 中**。

**补充命令：** 对已有研究空间的局部讨论添加新观点时，指定 `--space SPACE_ID`，原有整体研究问题保持不变。只有 `research overview-update SPACE_ID --title ... --question ... --expected-revision N --reason ...` 可以明确修改总体目标；`research context-link` 允许同一个 Context 属于多个 Space。外部研究资料用 `research reference-add` 注册为未核验引用，并用 `research reference-link` 附到专门的 Reference View。

**操作文档：** [V030_MIGRATION_GUIDE.md](V030_MIGRATION_GUIDE.md) · [HUMAN_EVALUATION_GUIDE.md](HUMAN_EVALUATION_GUIDE.md) · [RELEASE_NOTES_V030.md](RELEASE_NOTES_V030.md)

---

## 保留的 v0.2.4 功能与操作参考

# VKF v0.2.4 — Resilient Model Gateway + Data Lifecycle

本地知识边界引擎：SQLite 保管正式认知与事务，Obsidian Vault 为可读/可编辑的 Markdown 投影，模型用于提炼和比较，**不会自动将建议认定为用户理解或直接合并正式知识**。

> **数据安全提醒**：首次迁移或大量导入前，请手动备份 `vkf.db` 和 Vault。不要将 `.db`、`.settings.json`、API Key 或私人对话提交到 Git。

## 系统要求

- Python **3.10 或更新版本**；SQLite 支持 `STRICT`、JSON 与 FTS5 Trigram；无需第三方运行时包。
- Obsidian 桌面应用，用于检查生成的 Markdown 和 Bases（非运行 Storage Core 的必需依赖）。
- 仅在 `--extract llm` / `--compare llm` 下调用用户指定的兼容 Chat Completions API；会发送相关对话/候选文本到 API，可能计费。
- UTF-8：所有文本读写显式使用 UTF-8，修复 Windows 默认 GBK 的已知问题。

## 1. 升级现有数据库

在**解压目录或 `git clone` 项目根目录**，将路径替换成自己的：

```powershell
python -m vkf_storage --db "D:\VKFData\vkf.db" init
python -m vkf_storage --db "D:\VKFData\vkf.db" doctor
```

当前 Schema 为 **v6**。从 v0.2.3（v5）升级时，`init` 会先创建 `vkf.db.pre-v6.<随机>.db` 备份。更早版本将逐级升级，并在首次版本迁移之前备份。原数据和设置保留；切勿在重要数据库上跳过手动备份。**切勿在尚有重要数据时删除旧 DB 再初始化**。

## 2. 第一次配置关联 Obsidian 与模型

Vault **不需要**放在 Git 仓库内，也不需要额外插件：

```powershell
$DB = "D:\VKFData\vkf.db"
python -m vkf_storage --db $DB config set vault "C:\Users\YourName\Documents\My Vault"
python -m vkf_storage --db $DB config set model "gpt6-astra"
python -m vkf_storage --db $DB config set api-base "https://YOUR_PROVIDER/v1"
python -m vkf_storage --db $DB config set timeout 120
python -m vkf_storage --db $DB config set extract llm
python -m vkf_storage --db $DB config set compare llm
python -m vkf_storage --db $DB config show
```

关键设置存放在数据库旁边的 `vkf.db.settings.json`，可直接查看、复制和版本化设置方案（不含秘钥）。不要把它提交到公共仓库，因为它记录本机路径。每个数据库各有独立配置。

**API Key 绝不存入 SQLite / settings JSON：**

```powershell
$env:VKF_API_KEY = "你的 API Key"
```

Windows PowerShell 环境变量只对当前 PowerShell 会话有效。若是 Ollama 等本地兼容服务，`api-base` 可以使用 `http://localhost:端口/v1`，不要求远程凭证。远程端点必须是 HTTPS。

也可用环境变量以外的系统机密管理器来向进程注入 `VKF_API_KEY`；但切勿将密钥写入项目文件。

## 3. 旧对话导入 + 生成巩固建议

支持 ChatGPT 原生 `conversations.json` 当前分支、Claude 常见 JSON、带 `## User`/`## Assistant` 的 `.md`。自动创建候选，但**不自动批准**。

```powershell
python -m vkf_storage --db $DB import-history "D:\ChatExports" --consolidate
```

当已保存 `extract=llm` 和 `compare=llm` 时，这条命令会调用模型提炼及比较（**可产生多次付费 API 请求**）。建议初次运行时先保持 `config set extract heuristic` 和 `config set compare heuristic`，或先导入单个文件。

更稳妥的分阶段方式：

```powershell
# 首先只归档原文，不调用模型
python -m vkf_storage --db $DB import-history "D:\ChatExports" --extract none
# 对已归档的一部分对话使用新版本无截断提炼，再做巩固
python -m vkf_storage --db $DB pipeline run --all --extract llm --compare llm --limit 2
```

`pipeline run --all` 是专门用于已有历史重提炼的命令。由于 v0.2 使用全新 Prompt / chunk 指纹，会创建新的候选而不修改旧候选；巩固层应帮助你处理这种重复，而不是静默消除历史。每条对话单次完整 LLM 提炼最多 80 个 chunk，请关注费用与 API 速率限制。

## v0.2.4 更新：数据生命周期 + 模型容错

针对实际日志中的两类失败，新增**有限 HTTP 上游重试**（默认可额外重试 1 次）以及**无效 JSON 的一次安全重提示**。提供 `VKF_CHAT_JSON_MODE=json_schema`，但仅推荐用于明确支持 Chat Completions Structured Outputs 的服务。原始对话不会因为服务端 502 或模型返回格式错误而丢失；没有完成 JSON 解析，不会入库伪造的候选。

```powershell
# 使用合成对话的提炼和比较探针（可能产生少量 API 费用）
python -m vkf_storage --db $DB model-probe --task extract
python -m vkf_storage --db $DB model-probe --task compare

# 仅清除某场旧提炼，原始消息保留（必须先预览并使用当次令牌）
python -m vkf_storage --db $DB lifecycle plan --scope extraction --conversation-id CONV_ID
python -m vkf_storage --db $DB lifecycle apply --scope extraction --conversation-id CONV_ID --confirm TOKEN

# 或者完全重做认知层，保留所有原始对话
python -m vkf_storage --db $DB lifecycle plan --scope derived
python -m vkf_storage --db $DB lifecycle apply --scope derived --confirm TOKEN

# 最后把数据库已退休且未编辑的托管 Obsidian 文件移到 Vault 外备份
python -m vkf_storage --db $DB lifecycle vault-prune
python -m vkf_storage --db $DB lifecycle vault-prune --apply --confirm VAULT_PRUNE_TOKEN
python -m vkf_storage --db $DB bridge export
```

还可使用 `lifecycle --scope conversation --conversation-id CONV_ID` 删除一场原始对话，或 `--scope all` 在备份后清空整个当前数据库（配置和归档记录仍保留）。**所有清理命令都必须先预览、确认，并自动产生数据库备份。** 不会强删用户修改过的 Obsidian 文件。详见 [LIFECYCLE_GUIDE.md](LIFECYCLE_GUIDE.md)，此文档包含范围对照表、恢复数据库的步骤、错误排查和验收清单。

## v0.2.3 更新：区分「内部论证关系」与「跨对话知识巩固」

> **对实际日志的判断**：一场对话提取 7 个 Candidate，出现 4 条 REFINES、2 条 RELATED、1 条 NEW，并不表示发生了跨对话去重。旧版的来源上下文会人为提高同场对话候选的检索分数；v0.2.3 删除了这一加分，改为报告 `comparison_scope`。

```powershell
# 第一次使用新版源码时必须迁移数据库，自动生成 pre-v5 备份
python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor

# 只比较来自其他历史对话的可检索旧认知，不处理同一来源对话的局部展开
python -m vkf_storage --db $DB consolidate run --scope cross --mode llm --limit 15

# 查看待确认建议（comparison_scope：跨对话 / 同一对话 / 来源混合 / 无匹配）
python -m vkf_storage --db $DB consolidate list

# 对需要保留的 REFINES/RELATED 进行人工接受（仍不是正式知识）
python -m vkf_storage --db $DB consolidate decide REVIEW_ID accept --reason "独立观点但存在细化关系"

# 查看已经确认的候选间关系，刷新 Obsidian 中的可点击关系
python -m vkf_storage --db $DB consolidate links
python -m vkf_storage --db $DB bridge export
```

`--scope` 取值：`all`（默认，既考虑同场对话，也考虑跨对话）、`cross`（不共享原始对话的对象；排除未知来源）、`within`（共享原始对话的对象）。若对象从多场对话汇合，可能显示 `mixed`；它在 cross 和 within 查询中均可见。

**新的审核写入语义：**

- 接受 `SAME`：记录 canonical 同一性 / 归并来源；不删除原始对话。
- 接受 `REFINES` / `RELATED`，目标为 Candidate：写入 `candidate_links` 临时关系，并在候选和主题的 Markdown 投影中创建链接；**不修改正式图谱**。
- 接受 `REFINES`，目标为正式知识，且显式传入人工撰写 `--new-body-file`：执行带版本的正式修订。若没有该文件，则只保存待验证关系。
- 接受 `NEW`：只记录已审阅，不意味着候选自动成为用户认可的知识。
- `consolidate list/show` 中的 `effect` 表示实际写入动作：`provisional_relation`、`equivalence`、`formal_revision`、`acknowledged_only` 等。由旧版本接受的建议会标记为 `legacy_unknown`，不可据此推断已写入正式关系。

对于跨类型建议，例如 `Question → Idea`，模型即使返回 `REFINES`，系统也会保守降级为 `RELATED` 并标注原因；强制手动指定跨类型 `REFINES` 会被拒绝。Question 发起对 Idea 的追问，通常不意味着它已证明或修订了该观点。后续将设计显式 `raises`/`investigates` 问题关系。

`score` 仍只是词汇/标题相似度，不是概率，也不是语义证明。当前检索仍是轻量级词汇检索且存在数量上限：`NEW` 只能表示在**当前候选集合与检索阈值**下没有找到合适目标，不能证明整个 Vault 中没有相同观点。真正跨领域的关联仍需要后续 Embedding / 全局召回机制与人工评估。

升级后第一次按新策略运行时，**尚未审核的旧 Review 可能被新的 Review 取代并标记为 dismissed**（原始历史不会删除）；已接受的旧 Review 不会被重新自动提交。建议先备份数据库，用 `--limit 15` 观察变化，再扩大范围。无须重新提炼对话。

## 4. 认知巩固：检索、比较、人工审核

```powershell
python -m vkf_storage --db $DB consolidate run --mode heuristic
python -m vkf_storage --db $DB consolidate run --mode llm
python -m vkf_storage --db $DB consolidate list
python -m vkf_storage --db $DB topic list
python -m vkf_storage --db $DB bridge export
```

打开已有的 Obsidian Vault，然后浏览 `VKF/01 - Consolidation.md`、`VKF/Consolidation Inbox.base` 和 `VKF/Topics/`，以及原来的 `VKF/00 - Start Here.md`。

每条建议包含：`SAME`（命题等同）、`REFINES`（深化）、`CONTRADICTS`（冲突）、`RELATED`（相关）、`NEW`（新增）、`CROSS_DOMAIN`（跨域类比候选）或 `DISCARD`（低价值建议）。**检索分数不是事实概率，RELATED 不等于 SAME。** 离线比较只把几乎完全一致的命题建议为 SAME；语义释义的 SAME/REFINES 需 LLM 或人工审阅。

查看一条建议：

```powershell
python -m vkf_storage --db $DB consolidate show REVIEW_ID
```

假设它建议新候选与一条旧候选等价：

```powershell
python -m vkf_storage --db $DB consolidate decide REVIEW_ID accept --reason "核对后确认核心命题相同"
python -m vkf_storage --db $DB candidate list
python -m vkf_storage --db $DB candidate approve CANONICAL_CANDIDATE_ID
python -m vkf_storage --db $DB bridge export
```

接受 `SAME` 后，如果目标仍是 Pending Candidate：汇集双方来源，保留原始对话，尚不产生正式知识。随后批准规范候选时，等价候选将标记为合并。

当目标是正式 Knowledge：接受 SAME 才会把新候选合并到已有正式对象的来源。`REFINES` 需要你明确提交改写后的正文才会更新正式对象（使用 `--new-body-file`）。`CONTRADICTS` / `CROSS_DOMAIN` 的正式关系需要先批准双方候选才能添加；`RELATED` 的审核只确认主题归组，不会伪造有方向的正式语义关系。

若模型遗漏了关系，可明确补充一条人工建议：

```powershell
python -m vkf_storage --db $DB consolidate suggest NEW_CANDIDATE_ID SAME --target EXISTING_CANDIDATE_ID --reason "人工比较认为两者为相同命题"
```

注意：人工 `SAME` 的 Pending Candidate 目标必须早于来源候选。若推荐错误：

```powershell
python -m vkf_storage --db $DB consolidate decide REVIEW_ID dismiss --reason "主题相近，但关键结论不同"
```

来自模型的 `understanding` 候选需要显式确认：

```powershell
python -m vkf_storage --db $DB candidate approve CANDIDATE_ID --confirm-understanding
```

这仍只产生 `provisional` 理解，不意味着模型能客观证明用户已经掌握了该知识。

## 5. 无损分块、覆盖率验证

提炼时保存 `message_id` 与每段的字符起止位置，不再截断并丢弃大于 13000 字符的消息。原始对话始终保留。

```powershell
python -m vkf_storage --db $DB coverage CONVERSATION_ID
```

对完成 v0.2 LLM 提炼的对话，预期 `coverage: 1.0` 与 `complete: true`。这是**原文是否进入模型请求的字符覆盖率**，不代表模型是否成功提取其中的思想。旧版 v1 提炼记录没有覆盖区间，不能以零覆盖率推断原始资料丢失。

## 6. 量化效果与人工标注

参考 `acceptance/annotations.example.json`，从实际数据库取出 Candidate ID，人工标注应该 SAME / NOT SAME 的成对例子、低价值候选、长对话 ID：

```powershell
python -m vkf_storage --db $DB evaluate "D:\VKFData\my-annotations.json"
```

计算仅在你给出的标注对上进行：`same_precision`、`same_recall`、`retrieval_recall_at_8`、`false_same_proposal_rate`、`noise_precision`、`noise_recall`，以及对应长对话的覆盖率。**它们不能直接代表整个知识库的全局准确率。**

具体目标、范畴论测试案例和操作流程见 [ACCEPTANCE_PLAN.md](ACCEPTANCE_PLAN.md)。

## 7. 代码与回归测试

```powershell
python -m unittest discover -s tests -v
python examples/demo_consolidation.py --db ".\demo-v2.db" --vault ".\DemoVault"
```

运行单独的示例不会使用或覆盖你的正式 `vkf.db`。升级后的 Obsidian Bridge 仍然遵循以前的可编辑区域和严格冲突检查：

```powershell
python -m vkf_storage --db $DB bridge status
python -m vkf_storage --db $DB bridge pull --apply
```

## 8. v0.2 的已知边界（请据此评价）

- SQLite 是正式权威数据，Markdown 是 Obsidian 投影；未提供实时同步或 Obsidian 内直接批准按钮。
- `heuristic` 的 RELATED 基于标题、正文和来源对话上下文的词汇特征，不意味着相关性经过语义验证；只能自动建议完全一致的 SAME。
- `llm` 模式使用有限数量的检索候选供模型比较，**没有**接入完整 Embedding 检索、知识图谱推理或跨领域自动生成经过批准的 CrossInsight。
- Topic 是初步聚类导航；不同命题处于同一 Topic 不等于同一观点。
- `cross_insight` 的正式创建仍需要至少两个经过批准的对象及清晰的连接理由。
- 直接修改托管 Markdown 的状态或关联字段仍会产生冲突；只在 `VKF:EDITABLE` 范围内改动并显式 `bridge pull --apply`。
- 导入和提炼当前以文本为主；附件、分支历史及模型工具调用不能保证完整还原。建议保留原始 ChatGPT/Claude 导出文件。
- 模型所见信息受 API 请求内容影响；SQLite 存储模型调用的摘要指纹和配置，不保存远端提供商内部执行轨迹。

## 发布来源

本项目从 v0.1.2 Storage Core 继续演化：保留原本的 SQLite 审核、事务和 Obsidian Bridge，并添加 schema v4、`settings.py`、`consolidation.py`、`coverage.py`、`evaluation.py`、`obsidian_reviews.py` 和相应的测试。


## v0.2.1: model API diagnostics (Windows PowerShell)

The original v0.2.0 obscured three distinct errors (empty HTTP body, empty
`message.content`, and malformed model JSON). The gateway now reports the stage,
`finish_reason`, response format, output usage and sanitized request identifier.
Neither full replies nor private prompts are included in exception messages.

Before rerunning a full history pipeline, check the configured API with a tiny
synthetic request (this calls your provider and might be billed):

```powershell
python -m vkf_storage --db $DB config show
python -m vkf_storage --db $DB model-probe
```

The following **optional**, provider-specific environment variables affect only
the current terminal and are not written to a file:

```powershell
$env:VKF_CHAT_TOKEN_FIELD = "max_completion_tokens" # default: max_tokens
$env:VKF_CHAT_MAX_OUTPUT_TOKENS = "4096"       # default: extractor 2300, comparison 500
$env:VKF_CHAT_OMIT_TEMPERATURE = "1"           # default sends temperature: 0
$env:VKF_CHAT_JSON_MODE = "json_object"        # default: none
python -m vkf_storage --db $DB model-probe
```

**Only enable knobs supported by your API provider.** In particular, the
OpenAI-compatible Chat Completions endpoint is required; Responses-only or
streaming/SSE-only API endpoints are not supported by this version. Increase
token budget only if needed; usage and costs may rise. Never paste your API key
or unredacted private conversations into bug reports. To diagnose a failure,
share the command (without key), model ID, the API base hostname (if public),
`finish_reason`, response shape, HTTP status, and token counts.


### v0.2.2: Complex comparison API output format troubleshooting

The basic `model-probe` checks simple JSON; realistic comparison can fail despite that.
Run the synthetic comparison probe (no personal content is sent):

```powershell
$env:VKF_CHAT_JSON_MODE = "json_object"
$env:VKF_CHAT_MAX_OUTPUT_TOKENS = "2048"
$env:VKF_CHAT_TOKEN_FIELD = "max_completion_tokens"
$env:VKF_CHAT_OMIT_TEMPERATURE = "1"
python -m vkf_storage --db $DB model-probe --task compare
```

JSON mode is enabled by default in v0.2.2; set `$env:VKF_CHAT_JSON_MODE = "none"` if an older provider rejects it. If your provider does not support one of these settings, follow the reported HTTP
parameter error and disable that knob. On the actual knowledge base, run
`consolidate run --mode llm --limit 2` initially, review the returned `errors`
field, and only then increase batch size. The comparison probe uses synthetic
content, but real consolidation sends candidate text to your API provider.
The v0.2.2 runner does not automatically retry failed paid model calls.


### v0.2.2: failure behavior

A malformed response in one candidate comparison now appears in the `errors`
array with that candidate ID instead of stopping the entire batch. It is not
silently retried, merged, or approved. Check `model_calls` and the CLI diagnostic
for the response stage. Run `consolidate run --mode llm --limit 2` after a successful
`model-probe --task compare`, and then review new suggestions.
