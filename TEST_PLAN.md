# VKF Storage Core — 初步人工验收计划

测试的目标不是证明 VKF “已经提高认知水平”。首版只能验证：**长期知识存储是否可靠、增量审核是否可控、关系/问题模型是否值得继续开发、界面摩擦是否可以接受。**

## 准备

1. 在项目目录运行：`python -m unittest discover -s tests -v`。
2. 创建独立实验库：`python examples/demo_session.py --db ./vkf-human-test.db`。该路径如果已经存在，请换一个名字。
3. 记录 Demo 输出的 IDs。后续 `<id>` 占位符换成相应的真实 ID。
4. 建议选择 **你自己真实关心的一个 AI 话题**，例如 Agent Memory、数学推理、GPU/Ascend、长上下文或知识图谱。
5. 每个任务记录三件事：是否成功、实际耗时（手动计时即可）、哪里产生认知或操作负担。

## A. 工程可靠性：可客观判断通过/失败

| 测试 ID | 操作 | 预期结果 | 常见失败信号 |
|---|---|---|---|
| A1 持久化 | 新建一个 Idea，关闭进程，再运行 `object show <id>` | 原文/类型/ID/版本一致 | 丢记录、中文乱码、意外变更 |
| A2 未批准隔离 | `candidate list`，取 Demo Pending Candidate 的 title 用 `search` 查找；然后 `candidate approve <id>` 再查 | 批准前正式搜索**不返回**候选；批准后返回 | 自动将 AI 提议视为知识 |
| A3 导入去重 | 两次运行 `conversation import-json examples/sample_conversation.json` | 第一次 `created=true`，第二次 `created=false`，消息数量不增长 | 产生重复对话 |
| A4 关系方向 | 给两个 Knowledge 添加 `analogous_to`，反向重复添加同类关系 | 首次成功，反向重复返回冲突；`graph` 仍能从两端发现它 | 对称边重复或方向错误 |
| A5 更新与回滚 | 用 `object edit` 修改 Idea，`object history` 查看，再用 `object restore` 恢复旧版 | 每次实质编辑增加版本；恢复**生成新版本**，历史不丢 | 丢失上一版、覆盖全部历史 |
| A6 状态正确 | 新建 Question，立即 `question set <id> answered --reason ...`（不附解决说明）；之后关联一个有效 `answers` 边再试 | 无依据回答被拒绝；有依据后允许；`answered` 可以明确 reopen | 未经认可便“自动解决” |
| A7 洞察来源 | 新建 CrossInsight 时只传 1 个 `--source-id`，然后传 2 个不同来源 | 1 个来源失败并不落库；2 个来源成功，图谱存在两条 synthesizes 边 | 悬空节点、部分写入 |
| A8 数据安全 | 运行 `backup`、`restore-db`（新路径）并 `doctor`，对比 `stats` | 恢复库 `ok=true` 且记录数一致，覆盖已有路径被拒绝 | 数据缺失、覆盖、损坏 |
| A9 检索边界 | 依次搜索 `KV`、`物化`、`100%`、不存在的词，再修改某对象的 title | 正确返回/无结果，百分号按字面量，旧标题不再命中 | 字符串误解释为 SQL/过滤失效 |
| A10 旧库迁移 | 在副本或实验 v1 库上运行 `init` | 自动生成 `.pre-v2.*.db`，新 Schema 为 2，旧数据仍在 | 破坏旧库、未备份、静默修改 |

所有 A 类用例都应达到“通过”；如果失败，在扩大认知内容规模之前先修复。

### 示例命令和对象状态流

```text
# Demo 的 open_question ID 可用于：
python -m vkf_storage --db ./vkf-human-test.db question set <open_question_id> exploring --reason "开始研究内存生命周期"
python -m vkf_storage --db ./vkf-human-test.db question set <open_question_id> answered --reason "尝试无依据关闭"
# 上一条应失败；真正解决时传 --resolution-note 或先建有效 answers 边。

# 使用 --expected-revision 避免覆盖别人或另一个 CLI 进程的更新
python -m vkf_storage --db ./vkf-human-test.db object edit <kv_cache_id> --title "KV Cache（补充）" --reason "标题更清晰" --expected-revision 1
python -m vkf_storage --db ./vkf-human-test.db object edit <kv_cache_id> --title "故意触发冲突" --reason "重试旧版本" --expected-revision 1
# 后一条应报告 Conflict 且不改变当前对象。
```

## B. 认知模型质量：需要你的真实评价

这些测试为下一阶段的产品/研究选择提供反馈，不要求首版 AI 自动运行。

**B1 · Knowledge vs Idea 区分**：从自己的 1 段真实对话里手动挑出约 5 条信息，分别标记 Knowledge、Idea、Understanding 和 Question。哪些内容分类很自然？哪些内容难以归类？是否有一种对象缺失？

**B2 · 原子化粒度**：将一个复杂 AI 主题拆成多个对象。问自己：“这个知识卡片能独立被理解吗？”记录分拆太碎或太大的例子。后续 Extractor 需要据此建立粒度策略。

**B3 · CrossInsight 的含金量**：建立 2 个跨领域链接，明确写下：共同结构、重要差异、一个值得继续探索的问题。评价这种形式是否真的提供启发，还是仅仅产生了漂亮但无用的连接。

**B4 · Question 重访价值**：保存约 3 个开放问题，隔一段时间加入相关的新知识，然后手工运行 `frontier suggest`。评价其中有几个提示真正让你想进一步追问，以及哪些只是泛泛相关。

**B5 · 信息噪声与审核负担**：为 1 段对话人为创建多个 Candidate。用 approve/reject/merge 处理它们。记录从“读到原始内容”到“留下少量值得保存的认知对象”花了多少时间；记录不愿意保留的候选原因。这些反馈比对象计数更重要。

**B6 · 检索失配**：写下 5 条你希望通过知识库找回的问题，并实际运行 `search`。记录当前“子串检索”无法命中的语义同义表达（例如“缓存失效” vs “状态过时”）。这将帮助判断 Embedding / Context Builder 的优先级。

## C. 推荐反馈量表

每个维度 1～5 分，1=非常差，5=非常好；不适用填 N/A。

| 维度 | 问题 |
|---|---|
| 使用摩擦 | 记录一个观点是否足够便捷？ |
| 认知对象清晰度 | Knowledge / Idea / Understanding / Question / CrossInsight 是否容易区分？ |
| 关系有效性 | 带解释的关系是否帮助组织观点？ |
| 问题持续性 | Open / Exploring / Answered / Parked 是否符合实际探索习惯？ |
| 数据可信度 | 是否能够相信审核、版本、备份机制？ |
| 检索实用性 | 能否重新找到想找的内容？ |
| 发展潜力 | 你是否愿意为下一次真实思考继续使用它？ |

**下一版决策建议：**

- 如果“使用摩擦”最低，优先改善交互入口（TUI / Web UI）。
- 如果“检索实用性”最低，优先 Hybrid Search + Context Builder。
- 如果“提炼耗时与审核负担”很高，优先开发增量 Extractor + 候选去重。
- 如果“关系有效性”最低，先修改关系语义与 CrossInsight 生成规则，不急着做自动 Linker。
- 如果“数据可信度”有失败，优先补测试与修复，不引入新功能。

请在反馈中给出至少 1 个具体例子（可改写和脱敏），比笼统好评或差评更有帮助。
