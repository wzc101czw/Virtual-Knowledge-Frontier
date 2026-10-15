# VKF v0.2.0 — Cognitive Consolidation

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

从 v0.1.2 的 schema v3 升级为 schema v4；对已有 DB 会先自动生成 `vkf.db.pre-v4.<随机>.db` 私有备份。原数据保留。**切勿在尚有重要数据时删除旧 DB 再初始化**。

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
