# VKF v0.2.4 · 数据生命周期与模型容错（Windows PowerShell）

## 0. 前置检查

请在新的 VKF 代码目录执行命令，确保使用 **v0.2.4**。**先在副本数据库 / 副本 Vault 上测试**：

```powershell
$DB = "D:\VKFData\vkf.db"     # 替换为已有数据库真实路径
python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor
python -m vkf_storage --db $DB config show
```

`init` 升级原有 v5 → v6 前会生成 `*.pre-v6.*.db`，不会清空旧数据。Vault、模型、API Base 设置保存在 `vkf.db.settings.json`，迁移后继续有效；API Key 从环境变量提供，不被储存。

**当前清理是逻辑删除，而非可验证的安全擦除。** 自动备份、SQLite WAL、外部原始导出、手动笔记以及文件系统备份可能仍保存相关内容。恢复前不要清理备份。

## 1. 四类数据清理范围

| `--scope` | 清理 | 保留 | 保护措施 |
|---|---|---|---|
| `extraction` | 某一对话的提炼运行、候选和依赖它们的候选间 Review | 原始对话与消息、其他正式知识 | 已批准/合并的候选会阻止删除 |
| `conversation` | 指定原始对话、消息及其提炼/候选/Review | 其他对话、其他已批准的知识 | 若被正式知识引用则阻止删除 |
| `derived` | 所有候选、提炼、知识、关系、问题、主题、Review 及模型调用日志 | **全部原始对话、消息、导入记录与设置** | 必须预览 + 显式确认 + 自动备份 |
| `all` | 上述所有数据 **及所有对话/消息/导入记录** | 设置 JSON、生命周期操作记录与备份 | 最高风险；必须预览 + 显式确认 + 自动备份 |

注意 `--scope derived` 会清除**已批准**的认知对象，不能只视作清除 Pending Candidate。如果你仅想重新提炼某一场、且此前没有批准其候选，优先选择 `extraction`。

## 2. 清理错误提炼，保留对话（优先推荐）

查看已有对话 ID：

```powershell
python -m vkf_storage --db $DB conversation list
```

仅清理某场对话的旧提炼结果：

```powershell
$CONV = "conv_实际ID"
python -m vkf_storage --db $DB lifecycle plan --scope extraction --conversation-id $CONV
```

将输出的 `token` **复制**到下面命令，而不是猜测或复用旧 token：

```powershell
python -m vkf_storage --db $DB lifecycle apply --scope extraction --conversation-id $CONV --confirm "刚才输出的token"
```

返回 JSON 包含完整备份路径、受影响记录计数及 `doctor` 结果。手动确认 `doctor.ok=true`。如果提示已有正式知识依赖该对话，这次删除会被阻止，避免不小心破坏已有理解。

此时你可以安全地重新调用提炼（可能产生 API 费用）：

```powershell
python -m vkf_storage --db $DB extract $CONV --mode llm
```

## 3. 想从头重做所有认知，保留聊天历史

```powershell
python -m vkf_storage --db $DB lifecycle plan --scope derived
python -m vkf_storage --db $DB lifecycle apply --scope derived --confirm "预览中实际返回的token"
```

这里是**完全重建认知层**，不仅删除 Candidate，还包括你已经手动批准的 Idea / Knowledge / Understanding。需确保备份和确认令牌有效。

若要连原始对话一起彻底从**当前数据库**清空，使用 `--scope all`；它也会生成备份，但不保证清除其它位置的原始导出及备份文件。

## 4. 将已经退休的 Obsidian 笔记安全移出 Vault

**先执行此步，再运行 `bridge export`**。桥接系统不会自动强删过时笔记，而是保留导出时的 SHA-256 指纹用于安全判断。

```powershell
python -m vkf_storage --db $DB lifecycle vault-prune
```

命令显示 `ready / missing / conflict_modified / conflict_unsafe` 四种计数以及确认令牌。

```powershell
python -m vkf_storage --db $DB lifecycle vault-prune --apply --confirm "刚才输出的token"
```

- `ready`：与最近受管导出完全一致的生成文件，会移出 Vault 到 Vault 同级的 `MyVault-VKF-retired-...` 目录；不会永久删除。
- `conflict_modified`：有人修改了文件；**拒绝移动**，需要人工检查。若继续 `bridge export`，旧文件也可能导致冲突。
- `conflict_unsafe`：符号链接、越界路径、编码异常等；拒绝操作。
- 普通非 VKF 笔记不会被枚举，也不会被移动。

清理后刷新：

```powershell
python -m vkf_storage --db $DB bridge export
python -m vkf_storage --db $DB doctor
```

`Consolidation Inbox.base` / `Candidate Inbox.base` 等导航文件仍由 Bridge 管理，用户手改导致的冲突需保留备份并单独处理，不能以清理全部旧认知为理由强制覆盖。

## 5. 恢复数据库（不覆盖现有文件）

如果需要回到清理前的状态，使用生命周期操作返回的 `backup` 路径，并指定**新的**目标数据库路径：

```powershell
python -m vkf_storage --db "D:\VKFData\vkf-restored.db" restore-db "D:\VKFData\vkf.db.before-lifecycle-YYYY...db"
```

再对新数据库调用 `doctor`。切换数据库后确认保存的 Vault 路径是否仍然适合使用。已移出 Vault 的 Markdown 可以从旁边的归档目录恢复，**不要直接使用旧数据库强制覆盖仍有人工修改的笔记**。

## 6. 模型容错与诊断

`502 upstream_error` 是服务端 / 网关异常；系统只对 429、500、502、503、504 进行有限 HTTP 重试，尊重不超过短时等待上限的 `Retry-After`。401、403、400 等不重试。网络超时可能在上游已计费，为降低重复消耗，不自动重试未知状态的超时。

`200 invalid JSON` 会触发**一次**额外的更严格生成尝试（默认）。它不会从任意自然语言中盲目截取看起来像 JSON 的内容；如仍失败，只记录错误并将本次候选保留为未完成，允许手动重跑。

示例（PowerShell 环境变量仅作用于当前会话）：

```powershell
$env:VKF_API_KEY = "你的私有 API Key"
$env:VKF_CHAT_TOKEN_FIELD = "max_completion_tokens"  # 服务端支持时使用
$env:VKF_CHAT_OMIT_TEMPERATURE = "1"
$env:VKF_CHAT_JSON_MODE = "json_object"       # 默认
$env:VKF_CHAT_HTTP_RETRIES = "1"              # 默认，0..3
$env:VKF_CHAT_JSON_RETRIES = "1"              # 默认，0..1
python -m vkf_storage --db $DB model-probe --task extract
python -m vkf_storage --db $DB model-probe --task compare
```

若你使用的服务**明确支持 Chat Completions Structured Outputs**，可以选择：

```powershell
$env:VKF_CHAT_JSON_MODE = "json_schema"
```

如果服务商返回 400 `unsupported_parameter`，请恢复 `json_object` 或 `none`，并参照提供商文档。注意 JSON Schema 仅约束**格式**，不能保证认知观点正确、去重合理。

额外请求可能产生额外费用。最坏情况下，一次逻辑模型调用可包含若干次 HTTP 重试和一次格式纠正尝试；可用 `VKF_CHAT_HTTP_RETRIES=0` 与 `VKF_CHAT_JSON_RETRIES=0` 关闭自动重试。

对于仍然失败的请求，建议分享脱敏后的 HTTP 状态、`finish_reason`、JSON 解析位置、所用 API 协议和配置，不需要分享 API Key 或私密对话正文。

## 7. 质量验收简表

- [ ] 同一输入成功后重复运行，不创建第二份等价提炼结果
- [ ] 502 重试的上限严格受控，不对 HTTP 400/401/403 自动重试
- [ ] 模型正文不是 JSON 时不创建半成品 Candidate
- [ ] `derived` 清理后，原对话和消息数量保持不变、正式认知与候选归零
- [ ] `conversation` 清理若触及正式知识来源，操作被拒绝
- [ ] 每次真正删除前产生新的、可通过 Doctor 检查的数据库备份
- [ ] 预览后如果数据库中受影响的内容发生变化，旧确认 token 失效
- [ ] 修改过的 Obsidian 笔记不会被自动归档或覆盖
- [ ] 清理、归档并刷新后，Vault 不再显示被删除的受管 Candidate / Review 笔记

