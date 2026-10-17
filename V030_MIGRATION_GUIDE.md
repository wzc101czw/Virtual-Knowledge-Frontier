# VKF v0.3.0 · 升级、运行与回滚

## 升级前的注意事项

- 本版使用 SQLite **Schema v7**，是 v0.2.4（v6）的向前迁移。正式运行前应备份 SQLite 数据库及 Vault。迁移时自动生成 `vkf.db.pre-v7.<随机>.db`，但它不是个人备份制度的替代品。
- 保留之前保存的 `.settings.json`，其中包括默认 Vault、模型 ID、API Base；API Key 仍只从 `VKF_API_KEY` 环境变量读取。
- 请使用 v0.3.0 的 Python 源码，**不要在 v0.2.4 代码中打开已迁移到 v7 的数据库**。
- 旧 Candidate、Conversation、Consolidation Review 不会被自动改成 Research Space，不会自动清空历史。

## Windows PowerShell 示例

```powershell
$DB = "D:\VKFData\vkf.db"
python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor
python -m vkf_storage --db $DB config show

# 真实 API 探针只发送一段合成研究对话
python -m vkf_storage --db $DB model-probe --task research

# 选择一场你熟悉、愿意让模型处理的对话
python -m vkf_storage --db $DB research suggest-spaces CONV_ID
python -m vkf_storage --db $DB research map CONV_ID --mode llm
python -m vkf_storage --db $DB research map-list

# 或者先无 API 生成粗略骨架，了解审核命令
python -m vkf_storage --db $DB research map CONV_ID --mode heuristic
```

对已存在的研究空间继续一场新对话的讨论，显式传入 `--space SPACE_ID`：

```powershell
python -m vkf_storage --db $DB research map NEW_CONV_ID --mode llm --space SPACE_ID
```

**选择旧 Research Space 要经过人工判断**：`suggest-spaces` 只是词汇候选发现，不会自动合并。

## 审阅与研究前沿

```powershell
python -m vkf_storage --db $DB research map-show RMAP_ID
python -m vkf_storage --db $DB research map-export RMAP_ID "D:\VKFData\plan.json"
# 编辑后：
python -m vkf_storage --db $DB research revise RMAP_ID "D:\VKFData\plan.json" --expected-revision 1
python -m vkf_storage --db $DB research review-plan RMAP_ID
python -m vkf_storage --db $DB research review-apply RMAP_ID --confirm TOKEN --expected-revision 2 --reason "审阅确认"

python -m vkf_storage --db $DB research list
python -m vkf_storage --db $DB research show SPACE_ID
python -m vkf_storage --db $DB research assess SPACE_ID --mode llm
python -m vkf_storage --db $DB research synthesize SPACE_ID --mode llm
python -m vkf_storage --db $DB research frontier SPACE_ID
python -m vkf_storage --db $DB bridge export
```

人工接受某条相容性/综合/研究前沿提案：

```powershell
python -m vkf_storage --db $DB research decide synthesis SYNTH_ID accept --reason "有条件认可此综合假设"
```

接受一个 Synthesis 也**不会**自动证明你理解该观点，更不会写入正式 Understanding。

## 模型连接和输出控制

默认兼容 Chat Completions，`VKF_CHAT_JSON_MODE=json_object`。如果提供商确实支持严格结构化 JSON，可尝试 `json_schema`；不支持时可能返回 HTTP 400，请撤销该设置。

```powershell
$env:VKF_API_KEY = "YOUR_API_KEY"
$env:VKF_CHAT_JSON_MODE = "json_object"
$env:VKF_CHAT_HTTP_RETRIES = "1"
$env:VKF_CHAT_JSON_RETRIES = "1"
```

一场非常长的讨论会多次调用模型进行局部 Mapping，另有一次全局归组请求，可能计费。原始消息完整覆盖、单场最多 80 个内容分块。模型输出格式失败不会建立半成品研究结构；模型调用日志只存摘要指纹和状态，不存原始 Prompt 或 API Key。

## 回滚

如果 v7 迁移后出现重大问题，**不要尝试直接修改 `PRAGMA user_version`**。关闭 VKF，保留 v7 数据库作为证据，把迁移前 `.pre-v7...db` 通过 `restore-db` 恢复至一个新的文件路径，再使用 v0.2.4 代码测试恢复后的副本。恢复将丢失升级后才生成的 v7 研究空间内容；请先备份，确认后再切换。

```powershell
python -m vkf_storage --db "D:\VKFData\rollback-v6.db" restore-db "D:\VKFData\vkf.db.pre-v7.XXXXXXXX.db"
```

注意：恢复目标文件**不能已存在**，请使用新路径。设置 JSON 与 Vault 不会随恢复自动重绑定，需要检查 `config show`。

## 生命周期清理

`lifecycle --scope derived` 会包括新版研究空间、研究提案及其反馈，所以使用前务必预览受影响的 `research_spaces`、`research_maps`、`researcher_feedback` 计数。**谨慎删除研究员评审意见**，备份后才提交。

`lifecycle --scope conversation` 若目标对话已成为 Research Space 的证据或仍有 Research Map 审阅记录，将拒绝删除以保护来源。`lifecycle vault-prune` 会把未被修改的旧研究空间受管 Markdown 归档到 Vault 外，仍不会强制删除人工编辑过的文件。

## 研究空间长期演化与多重归属

新对话对既有 Space 的 `research review-apply` **仅合并新 Context / View**，默认保留该 Space 的原来总问题和目标。研究员如需明确修订总体问题：

```powershell
python -m vkf_storage --db $DB research overview-update SPACE_ID `
  --title "新的研究空间标题" --question "重新审视后的总体问题" `
  --goal "长期研究目标" --expected-revision 2 --reason "人工确认总体框架已变化"
```

同一个 Context 可以通过明确的人类动作同时属于多个研究空间：

```powershell
python -m vkf_storage --db $DB research context-link SPACE_ID CONTEXT_ID `
  --expected-revision 2 --reason "跨领域研究情境复用"
```

此功能不声称两个研究空间属于等价的数学 site；只保留它们共享的局部研究情境身份。

外部研究引用先登记为**未核验**：

```powershell
python -m vkf_storage --db $DB research reference-add --title "SAGE-nano" --type paper
python -m vkf_storage --db $DB research reference-list
# 对已审核的 Reference View 建立明确对应
python -m vkf_storage --db $DB research reference-link VIEW_ID REFERENCE_ID
```
