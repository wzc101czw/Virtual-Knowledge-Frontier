# VKF Storage Core v0.1.1 · 小版本更新

## New

- Obsidian Bridge：SQLite 正式认知对象 → 带 YAML Properties、Wiki Links、来源/关系说明的 Markdown。
- Obsidian 受控回写：`bridge pull` 预览、`--apply` 按期望版本创建新 revision；元数据、关系、哈希冲突保护。
- Conversation Archive & Candidate Inbox：本地 Vault 自动生成导航与只读归档；检测自动生成文件的外部改动，避免静默覆盖。
- JSON + Markdown 历史：ChatGPT 原始 mapping/current_node、Claude 常见 chat_messages、规范化 JSON、常见角色标题 Markdown、递归目录。
- Candidate-first 自动化：默认离线规则标注；可选 `--extract llm`，对 OpenAI-compatible API 以结构化候选形式提议，**不会自动批准**。
- `conversation_origins` 用于外部 ID 冲突发现；`message_import_metadata` 保存可用的历史时间戳；`model_calls` 日志在 API 提炼模式记录调用状态。
- Schema v3；为已有 v0.1.0 SQLite v2 自动备份并迁移。

## Kept from v0.1.0

认知对象五类型、七种关系、Question 状态机、Candidate 审核、SQLite 强约束、备份恢复、中文搜索及审计。既有 CLI 仍保留。

## Known limits

- 没有 Obsidian 插件或实时同步守护进程；Obsidian UI 集成是通过普通文件完成，未在真实安装的 Obsidian 内自动化点击测试。
- 非文本/附件导入不是完整复刻，ChatGPT 仅保留当前分支。
- 规则提炼是保守文本识别；LLM 提炼需要有效模型兼容接口、密钥与人工审核。无法保证语义去重和事实正确性。
- SQLite 与文件系统写入非跨系统原子；崩溃/并发时需要重新扫描、恢复，推荐定期备份。
- 文件名重命名/移动、图关系 GUI 编辑、自由 Markdown 同步、Candidate GUI 批量审批、自动生成 CrossInsight 尚未完成。
