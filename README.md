# VKF Storage Core v0.1.0

**Virtual Knowledge Frontier：可独立运行的个人认知存储核心。**

这是一个小型、完全离线的 Storage Core 实现，不是完整的 VKF 聊天软件。它把知识、想法、理解、开放问题和交叉观点存进本地 SQLite，提供可检索、可恢复、有约束的关系与版本历史，并把模拟模型提议隔离在 Candidate 区域。

## 你拿到的是什么

- ✅ 5 类正式认知对象：Knowledge / Idea / Understanding / Question / CrossInsight。
- ✅ 关系网络：supports、depends_on、contradicts、analogous_to、synthesizes、raises、answers。
- ✅ 正式对象版本修订、乐观并发校验、按旧版本产生**新版本**的恢复。
- ✅ Question 状态转换、回答依据校验；CrossInsight 至少需要两个来源。
- ✅ Conversation、Message 和规范化 JSON 对话导入（含重复检测）。
- ✅ Candidate 的提出、接受、拒绝、合并，**未批准的候选不能进入正式搜索结果**。
- ✅ 中文子串/英文搜索、1~2 跳关系探索、手工 Frontier 建议和审核。同一来源对象、目标问题、信号的重复 Frontier 提议只保留一条，避免只是措辞不同就反复提醒。
- ✅ 本地 SQLite 事务、数据库完整性检查、在线备份、备份恢复、JSON 导出。
- ✅ API 及 CLI，纯 Python 标准库，**无网络访问**。

**首版尚不支持：** 自动对话模型调用、自动 Extractor/Linker、任意平台原生聊天导出格式、向量/语义搜索、GUI、自动 Frontier 排序与自动 Agent。`candidate propose` 只是用来模拟模型候选，**不会真的调用模型**；`frontier suggest` 也是手工触发。

## 环境

- Python >= 3.10，需内置支持 SQLite `STRICT`、JSON 和 FTS5 `trigram` 的 SQLite。建议 SQLite >= 3.38。
- Windows / Linux / macOS 均可尝试；当前自动化测试环境为 Python 3.13 + SQLite 3.46。
- 无需 `pip install`，也无需 API key。

查看本机版本：

```bash
python -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
```

若出现 `no such tokenizer: trigram` 或 `near STRICT: syntax error`，说明本机 SQLite 版本或构建不符合最低要求；不会暗中用一个功能不完整的数据库继续运行。

## 5 分钟开始

解压后在 **项目根目录** 打开终端，执行：

```bash
# 初始化一个完全独立的数据库
python -m vkf_storage --db ./vkf.db init

# 新建一条知识
python -m vkf_storage --db ./vkf.db object add knowledge --title "KV Cache" --body "它可以复用历史注意力的 K/V 状态。"

# 搜索中文（也支持短中文词）
python -m vkf_storage --db ./vkf.db search "KV"
python -m vkf_storage --db ./vkf.db search "注意力"

# 查看所有正式对象
python -m vkf_storage --db ./vkf.db object list

# 健康检查
python -m vkf_storage --db ./vkf.db doctor
```

CLI 一律输出 JSON，适合阅读，也适合以后由 GUI 或脚本调用。对象 ID 由程序产生，在 JSON 结果的 `id` 字段中，可以复制到后续命令里。

如果喜欢简短的命令，可以在 Python 环境中执行 `python -m pip install -e .`，之后直接调用 `vkf --db ./vkf.db ...`。这一步是可选的，并可能需要本机已安装构建工具；不必依赖它才能测试。

### 用完整示例自动构建认知网络

```bash
python examples/demo_session.py --db ./vkf-demo.db
python -m vkf_storage --db ./vkf-demo.db stats
python -m vkf_storage --db ./vkf-demo.db candidate list
python -m vkf_storage --db ./vkf-demo.db search "缓存"
```

示例会新建两个 Knowledge、一个 CrossInsight、一个 Question、一条模拟对话、一个**待审核** Candidate 和一个 Frontier 建议，并打印所有 ID。为了保护已有数据，示例脚本拒绝覆盖现有数据库；请改用新的 `--db` 路径重新运行。

### 已有对话怎么导入？

首版只接受 **VKF 规范化 JSON**，示例在 `examples/sample_conversation.json`：

```bash
python -m vkf_storage --db ./vkf.db conversation import-json examples/sample_conversation.json
python -m vkf_storage --db ./vkf.db conversation list
```

格式为：

```json
{
  "source": "other",
  "title": "学习记录",
  "messages": [
    {"role": "user", "content": "为什么需要长期记忆？"},
    {"role": "assistant", "content": "可以考虑存储成本与推理成本的权衡。"}
  ]
}
```

字段 `source` 可用 `live/chatgpt/claude/other`；消息 `role` 可用 `system/user/assistant/tool`。

此功能**不是** ChatGPT 或 Claude 原始 JSON 的原生解析器，需要先整理成以上规范化结构。系统保存消息正文到数据库，并记录文件来源路径和哈希；**不会自动复制原始 JSON 文件**，如果要保存原件需自行归档。

相同内容重复导入时，返回 `created: false`，不会多建一份对话；调整 `title` 不会破坏这一去重规则。

## 人工模拟 Candidate 审核

先通过 `conversation import-json` 导入示例，记录输出中的 `conversation_id`；然后运行：

```text
python -m vkf_storage --db ./vkf.db conversation show <conversation_id>
```

在返回结果里寻找某条消息的 `id`，然后：

```text
python -m vkf_storage --db ./vkf.db candidate propose <conversation_id> <message_id> idea --title "记忆缓存策略" --body "或许可以把长期记忆淘汰视为成本优化。"
python -m vkf_storage --db ./vkf.db candidate list
python -m vkf_storage --db ./vkf.db candidate approve <candidate_id>
python -m vkf_storage --db ./vkf.db search "记忆缓存"
```

注意：批准前，`search` 无法找到这条 Candidate；批准后才会创建正式对象。批准、拒绝和合并都是终态，重复决策应报告冲突。

关系操作样例（使用 `object add` 返回的 ID）：

```text
python -m vkf_storage --db ./vkf.db relation add <knowledge_id> <question_id> raises --reason "这条知识产生了进一步的问题"
python -m vkf_storage --db ./vkf.db graph <knowledge_id> --depth 2
```

命令 `--reason` 是**必填的语义解释**，不是可省略的附加备注。

## 版本、备份和恢复

```text
# 修改对象，必须说明原因，可选指定当前 revision 防止覆盖并发修订
python -m vkf_storage --db ./vkf.db object edit <id> --body "更新过的理解" --reason "发现了一个反例" --expected-revision 1

# 查看不可变的历史
python -m vkf_storage --db ./vkf.db object history <id>

# 从第一版恢复，将生成一个更高的新 revision，而不是删除历史
python -m vkf_storage --db ./vkf.db object restore <id> 1 --reason "回到先前的解释"

# 制作 SQLite 备份，不允许覆盖同名已有文件
python -m vkf_storage --db ./vkf.db backup ./vkf-backup.db

# 恢复备份到一个全新的数据库路径
python -m vkf_storage --db ./restored.db restore-db ./vkf-backup.db

# 可读 JSON 全量导出（不是用于恢复的格式）
python -m vkf_storage --db ./vkf.db export-json ./vkf-export.json
```

`restore-db` **必须指向一个不存在的目标文件**。这避免误覆盖已有认知。恢复后可用 `doctor` 检查。可靠的数据恢复路径是 SQLite 备份；`export-json` 暂时仅为只读可移植快照，没有对应的全量导入命令。

### 旧 v0.1 Schema 的升级

如果曾使用上一次的 `vkf_schema_v0.1.sql` 建立数据库，现在执行：

```bash
python -m vkf_storage --db ./old-vkf.db init
```

检测到 `user_version=1` 时，会先自动生成 `old-vkf.db.pre-v2.<随机标识>.db` 私有备份，再以事务升级到 Schema 2；旧记录不会被主动删除。此前通过裸 SQL 手工创建但缺乏 `object_versions` 的对象仍可查询，但 `doctor` 可能报告缺少版本历史；这是**历史数据本身不符合新的版本管理约束**，首版不会替你猜测或伪造历史。

## 运行自动测试

```bash
python -m unittest discover -s tests -v
```

覆盖对象不变量、状态机、搜索特殊字符、中英文、导入幂等性、事务回滚、Candidate 隔离、CrossInsight 双来源、SQLite 备份恢复、迁移兼容和命令行错误码等。详见 `TEST_PLAN.md`。

## Python API 小例子

```python
from vkf_storage import Storage

Storage.initialize("my-vkf.db")
with Storage("my-vkf.db") as store:
    q = store.create_object("question", "为什么需要 Memory？", "何时保存，何时重新推理？")
    k = store.create_object("knowledge", "缓存权衡", "使用存储空间换取计算时间")
    store.add_relation(k["id"], q["id"], "raises", "计算复用引出了记忆保存策略问题")
    print(store.neighborhood(q["id"], depth=1))
    print(store.doctor())
```

## 行为原则及限制

1. **用户认知主权**：正式节点必须由用户显式创建或人工批准候选；没有自动写入记忆的模型任务。
2. **不把模型候选当成事实**：Candidate 单独存储；其 `proposed_relations_json` 目前不自动生效。
3. **不做学术溯源系统**：保存最小来源信息（对话、消息、审核记录、对象版本）。
4. **修改而非抹除**：删除未作为公开操作；通过归档和新版本保持历史。
5. **可复原**：关键多步骤写操作使用 SQLite 事务；备份使用官方在线备份机制。升级已有 Schema v1 数据库前自动建立一个私有备份。
6. **Local-first 不等于加密**：SQLite 文件、备份及 JSON 导出**均未加密**。它们包含对话和观点；请使用操作系统磁盘加密，不要将数据库直接放在公开同步目录。
7. **单机试验性质**：未进行大型语料、跨设备并发和对抗性输入安全认证，不宜立即作为唯一知识备份。
8. **非完整 Agent 系统**：Extractor/Linker/Context Builder 的模型调用将在后续版本引入。
9. **Context 日志做数据最小化**：`Storage.log_model_call` 只接受 SHA-256 十六进制输入指纹，以及确实存在的对象 ID/版本，不会代你记录完整私密 Prompt。

## 项目结构

```text
vkf_storage/
  __init__.py
  __main__.py
  cli.py                 # CLI 与 JSON 错误输出
  core.py                # Repository / transaction / state machine
  migrations/
    001_initial.sql      # 初始 Schema
    002_guardrails.sql   # 历史只追加与候选锁定保护
examples/
  sample_conversation.json
  demo_session.py
tests/
  test_storage.py        # 离线回归测试
TEST_PLAN.md             # 人工验收与主观认知收益测试
FEEDBACK_TEMPLATE.md     # 给下个版本的反馈记录
```

**下一版优先方向：** 根据你对 `TEST_PLAN.md` 的实际使用反馈，确定先做哪一个：更好用的交互 CLI/GUI、API 模型会话、增量提炼、语义去重、还是更智能的 Context Builder。
