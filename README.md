# VKF Storage Core v0.1.2

**SQLite Cognitive Core + Obsidian Bridge + `.json` / `.md` Conversation Import**

这是 VKF（Virtual Knowledge Frontier）的一个可直接测试的小版本：保留 v0.1.0 的 SQLite 认知对象、语义关系、状态机、审计和事务；增加本地 Obsidian Markdown 工作空间以及多来源聊天导入、自动候选提炼。

**设计原则：SQLite 是已确认知识和认知状态的权威记录；Obsidian 是人可以直接浏览和编辑的 Markdown 视图。** 原始聊天与 AI/规则提取的候选分离；候选需要人工确认，绝不会在导入时自动升级为用户已掌握的知识。

## Windows GBK 编码兼容提示 (v0.1.2)

本修复专门针对 Windows 中文系统下运行 `unittest` 时出现的
`UnicodeDecodeError: 'gbk' codec can't decode ...`：测试中的
Markdown/SQL 文件读取和写入都显式指定 UTF-8。生产代码此前已经使用 UTF-8。
如仍使用旧版，可临时运行 `python -X utf8 -m unittest discover -s tests -v`。

## 1. 环境

- Python **3.10+**，自带 SQLite 需支持 `STRICT`、JSON 和 FTS5 `trigram`（通常 SQLite 3.38+）。
- macOS、Windows、Linux 均可尝试；实现不依赖系统命令、外部 Python 库或 Obsidian 插件。
- Obsidian 桌面版：<https://obsidian.md/>。先不需要安装第三方社区插件。
- 默认**不调用互联网**。`--extract llm` 才向你明确配置的 OpenAI-compatible `chat/completions` API 发送对话文本。云端 API 可能产生费用。

在项目解压的根目录执行：

```bash
python -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
python -m unittest discover -s tests -v
```

如果报 `no such tokenizer: trigram` 或 `STRICT` 错误，需升级本机 Python/SQLite 构建。所有命令使用项目根目录的 `python -m vkf_storage`，**不需要 pip install**。

## 2. 五分钟：从聊天历史到 Obsidian

先在 Obsidian 中新建或选择一个**专用测试 Vault**（建议空文件夹），记下其绝对路径；也可以让命令先创建该文件夹，再在 Obsidian 选择 **Open folder as vault / 打开文件夹作为仓库**。

```bash
# 1. 新建本地知识数据库（第一次运行）
python -m vkf_storage --db ./vkf.db init

# 2. 导入 Markdown 对话并生成 Obsidian 的 VKF/ 文件夹
python -m vkf_storage --db ./vkf.db import-history ./examples/sample_dialogue.md --vault "./my-obsidian-vault"

# 3. 导入一组历史数据（文件夹递归，或单个 .json/.md）
python -m vkf_storage --db ./vkf.db import-history "./my-chat-exports" --vault "./my-obsidian-vault"

# 4. 查看等待你审核的提炼结果（规则默认仅提取显式观点/问题）
python -m vkf_storage --db ./vkf.db candidate list

# 5. 健康检查
python -m vkf_storage --db ./vkf.db doctor
```

在 Obsidian 里打开 `VKF/00 - Start Here.md`。你会看到：

```text
my-obsidian-vault/
  VKF/
    00 - Start Here.md     自动生成的导航入口
    VKF Objects.base       Obsidian Bases 数据表视图
    Open Questions.base    问题管理视图
    Candidate Inbox.base  待审核候选视图
    Conversations/         已导入的对话原文（Markdown 只读投影）
    Candidates/            待审核或已决议的提炼建议（只读投影）
    Knowledge/             正式知识
    Ideas/                 正式想法
    Understanding/         经过确认的理解
    Questions/             长期开放问题
    CrossInsights/         跨领域思想
```

**注意**：导入完成后，`Knowledge/` 不一定立即出现内容。这是刻意设计：候选会先进入 Candidate Inbox；只有人工批准才转成正式认知对象。自动入库 ≠ 自动采信。

通过 CLI 批准一条候选（从 `candidate list` 复制 `id`）：

```bash
python -m vkf_storage --db ./vkf.db candidate show <candidate-id>
python -m vkf_storage --db ./vkf.db candidate approve <candidate-id>
python -m vkf_storage --db ./vkf.db bridge export "./my-obsidian-vault"
```

批准后打开 `Knowledge/`、`Ideas/` 或 `Questions/` 中的新笔记。`VKF/00 - Start Here.md` 会同步更新。可在 Obsidian 设置中开启核心插件 **Bases**，打开 `VKF/VKF Objects.base`、`VKF/Open Questions.base` 和 `VKF/Candidate Inbox.base` 浏览结构化视图。**不要在 Bases 中直接修改 `vkf_` 托管属性**，这会触发 Bridge 冲突检查。

还可以测试已经存在的认知网络：

```bash
python examples/demo_session.py --db ./demo.db
python -m vkf_storage --db ./demo.db bridge export "./demo-obsidian-vault"
```

图关系通过 Obsidian 的 `[[内部链接]]` 呈现，类型、方向及建立理由在笔记的 `VKF Relations (generated)` 中完整保留。

## 3. Obsidian → SQLite 的受控编辑

每个正式对象笔记大致如下：

```markdown
---
vkf_id: "obj_..."
vkf_kind: "knowledge"
vkf_revision: 1
vkf_status: "active"
aliases: ["KV Cache"]
tags: [vkf, vkf/knowledge]
---

<!-- VKF:EDITABLE:START -->
# KV Cache

你在这里编辑解释和个人理解。

<!-- VKF:EDITABLE:END -->

## VKF Relations (generated)
- `raises` → [[VKF/Questions/...|待解决的问题]] — 联系的理由
```

仅修改 `<!-- VKF:EDITABLE:START -->` 和 `<!-- VKF:EDITABLE:END -->` **之间的 H1 标题和正文**。不要直接修改 YAML 中的 `vkf_id`、`vkf_revision`、`vkf_status`，也不要编辑自动生成的关系、来源和问题状态区域。这些字段必须通过 VKF 的状态机/关系接口修改；因此 Obsidian Properties 面板中的状态字段是*只读语义*，并不是 GUI 审核入口。

```bash
# 预览 Obsidian 中有什么人工编辑，不写数据库
python -m vkf_storage --db ./vkf.db bridge status "./my-obsidian-vault"
python -m vkf_storage --db ./vkf.db bridge pull "./my-obsidian-vault"

# 人工检查 ready/conflicts 后，确认落库为新 revision
python -m vkf_storage --db ./vkf.db bridge pull "./my-obsidian-vault" --apply

# 查看版本历史
python -m vkf_storage --db ./vkf.db object history <object-id>
```

`bridge export` **绝不默默覆盖已修改的正式对象笔记**；它会报告冲突。`pull --apply` 如果发现元数据改动、关系区改动、SQLite 版本过期、ID 不匹配等情况，也会拒绝相关笔记的更新。导出的原始对话、Candidate 和索引页面有单独的只读文件哈希保护，手动改动后同样不会被脚本覆盖。由于 SQLite 与文件系统无法跨系统原子提交，极端崩溃仍可能产生需要重新 export 的中间状态，正式工作请先备份，避免多个设备/进程同时修改。

如果你主动删除了一个生成的对象笔记，桥接不会默认悄悄恢复：

```bash
python -m vkf_storage --db ./vkf.db bridge export "./my-obsidian-vault" --restore-missing
```

**当前不支持**用户在 Obsidian 中自由重命名/移动 `VKF/` 下的托管对象文件；如果要调整标题，请修改可编辑区的 H1，而不是文件名。欢迎在 `VKF/` 之外自由创建其他个人笔记，不受 Bridge 管理。

## 4. 历史格式

新命令：

```bash
python -m vkf_storage --db ./vkf.db import-history <file-or-folder> [--source chatgpt|claude|other] [--extract none|heuristic|llm] [--vault ./vault]
```

支持：

1. **ChatGPT 原生导出 JSON**：含 `mapping` / `current_node` 的一个对话对象，或者整个 `conversations.json` 数组。遵循当前显示的分支沿 parent 链恢复顺序；非当前分支、非文本和隐藏工具消息跳过并报告；图片/附件二进制不导入。下载 ChatGPT 官方数据导出 ZIP 后，请先解压，找到 `conversations.json` 或分卷 JSON。
2. **Claude 常见 JSON**：`chat_messages` 数组，`sender` 为 human/assistant；解析文本 `content` 块。不同工具的 Claude 导出格式存在差异，非标准导出请用样例测试。
3. **VKF 规范化 JSON**：`{ "title": "...", "source": "other", "messages": [{"role":"user", "content":"..."}] }`。也支持通用 `conversations` 数组和简单角色消息数组。
4. **对话 Markdown**：`## User` / `## Assistant`、`## Human (时间):` / `## Claude (时间):`、`### 用户` / `### 助手`、`**User:**` / `**Assistant:**` 等角色标题；支持 `# 1. Human` 和前置 YAML `title` / `source`。代码围栏中的伪角色标题不会误拆。请参考 `examples/sample_dialogue.md`。
5. **目录递归**：自动筛选 `.json` / `.md`；遇到单个坏文件，报告该文件错误，继续处理其他文件。最多 5000 个文件，每个文件上限 120 MiB；大型 ChatGPT 导出可以先切成多个 JSON 文件。

如来源文件提供消息时间戳（例如 ChatGPT JSON 的 `create_time`、Claude 的 `created_at`、Markdown 角色标题里的时间），导入器会把它存入独立的消息元数据表，并在 Vault 归档中展示；没有日期的记录不会自动编造日期。对于没有明确时区的 Markdown 原文，原样保留时间字符串。

导入去重：先比较原始文件 SHA-256，再根据**来源 + 角色/正文序列**判定重复对话；同一来源、同一外部对话 ID 但内容被改动的再次导入会报告**冲突**，不会偷偷覆盖旧对话及其 Candidate。跨平台不同来源的同一语义对话尚不提供自动合并。

`conversation import-json` 仍保留，是 v0.1.0 的规范化 JSON 兼容入口；推荐新数据使用 `import-history`。

## 5. 自动候选提炼（Candidate-first）

### 默认：`--extract heuristic`

纯本地、无需 API key，保守提取**用户话语**中的显式问题（例如 `?`、`？`、`问题：`）和显式思想（例如 `我认为`、`我在想`、`假设`、`想法：`）。对于 `知识：`、`理解：` 等标注，也能生成相应种类的候选。它不会声称理解了所有自然语言，也**不会自动提取 AI 回复中的知识**；这适合做不会产生太多噪声的离线归档测试。

### 进阶：`--extract llm`

使用**你自己明确配置**的 OpenAI-compatible 模型端点，提取 `Knowledge / Idea / Understanding / Question`，带对话 turn 索引，最多分块发送（超长单轮会截断并给出 warning），存入 Candidate Inbox，等待人工批准。模型可产生错误、重复或空候选；这不代表它们已被事实验证或由你真正理解。

macOS / Linux（Windows PowerShell 用 `$env:VKF_API_KEY = '...'`）：

```bash
export VKF_API_KEY="YOUR_API_KEY"
python -m vkf_storage --db ./vkf.db import-history ./my-exports \
  --extract llm --model YOUR_MODEL_ID --api-base https://YOUR_PROVIDER/v1 \
  --vault "./my-obsidian-vault"
```

或对之前已导入的某一段对话再次提炼：

```bash
python -m vkf_storage --db ./vkf.db extract <conversation-id> \
  --mode llm --model YOUR_MODEL_ID --api-base https://YOUR_PROVIDER/v1
python -m vkf_storage --db ./vkf.db bridge export "./my-obsidian-vault"
```

本地 OpenAI-compatible 接口（如配置了相应兼容服务的 Ollama）可使用 `http://127.0.0.1:11434/v1` 和该服务真实支持的模型 ID。此应用仅对 HTTPS 或 localhost HTTP 发请求，不读取任何 Obsidian 账号信息；密钥从环境变量获取，不写入数据库。模型请求只记录 SHA-256 输入指纹与调用结果状态，不保存请求的全文副本。**不要将包含敏感信息的历史对话发往不信任的云端模型。**

解析器按要求使用 JSON Schema 形状 `{ "candidates": [...] }`，丢弃不合法的条目，保存有效候选及消息来源。暂不进行向量去重、自动 CrossInsight 构建、自动批准。未来会根据你的 Candidate 质量反馈改进增量提炼。

## 6. 更新已有 v0.1.0 数据库

**先手工另存一份数据库备份更稳妥**：

```bash
python -m vkf_storage --db ./vkf.db backup ./vkf-manual-backup.db
python -m vkf_storage --db ./vkf.db init
python -m vkf_storage --db ./vkf.db doctor
```

`init` 检测 Schema 2，会使用 SQLite 在线备份生成 `.pre-v3.<随机>.db`，再迁移到 Schema 3；Schema 1 先备份再逐步迁移。迁移不会主动删除对象、关系或对话。无需把旧数据库导成 JSON 重新导入，**也不要用文件复制替换正在被写入的 WAL 数据库**。

## 7. 常见问题与当前限制

- **Obsidian 中能直接按 YAML 属性修改问题状态吗？** 暂时不能。使用 CLI 的 `question set` / `object status`，再 `bridge export`。直接编辑生成元数据会拒绝同步。可以用 Obsidian Bases 查看过滤属性，但不应拿它绕过状态机。
- **能直接在 Obsidian 插件里聊天吗？** 本版本未开发或安装插件；可以独立配置 Copilot 等插件，但 AI 插件产生的记录需导出为支持的聊天 Markdown/JSON 再导入 VKF。Bridge 仅负责文件视图，不接管其他插件的内部聊天历史。
- **能自动把所有历史转成可靠知识吗？** 离线模式不能。LLM 模式会提议候选，但不自动认证；相似观点合并和跨域链接仍需后续算法或人工操作。
- **能无损还原所有 ChatGPT/Claude 多模态历史吗？** 不能。只导入当前分支中可见的纯文本消息，跳过二进制附件、图像、音视频以及部分工具内容。
- **能像普通 Obsidian 笔记一样随意改名移动文件吗？** 当前托管目录内不支持；Bridge 用稳定路径和记录过的哈希判断改动。自由笔记请写在 `VKF/` 外。
- **这是自动同步工具吗？** 不是。需要显式执行 `bridge export`、`bridge pull`。一开始采用人工确认的单向/受控双向流程，避免误覆盖。
- **是否内置加密？** 否。SQLite 和 Vault 都在本机以明文保存；请使用操作系统磁盘加密、合理备份和 Vault 隐私设置。

## 8. 反馈与复现

自动测试：

```bash
python -m unittest discover -s tests -v
```

优先跟随 `TEST_PLAN.md` 的人工验收任务，用 `FEEDBACK_TEMPLATE.md` 填写测试结果。如果出现问题，请仅分享错误输出、**匿名样本**和复现步骤，不要发送完整私人聊天历史或 API 密钥。

原始对话消息在 `messages` 表中有序保存；正式对象通过 `object_sources` 与已批准候选关联到来源消息，Obsidian 对象笔记中会生成指向对话归档的链接。项目许可证见 `LICENSE`。
