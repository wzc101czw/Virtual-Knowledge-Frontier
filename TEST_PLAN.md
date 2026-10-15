# VKF v0.1.1 人工验收测试计划

本计划用于发现**架构设计**和**认知体验**问题，不只是确认命令没有报错。请使用一份新的数据库与独立 Obsidian 测试 Vault。每项记下 PASS / FAIL、意外行为、截图或匿名复现信息。务必保存原始对话的独立备份，不要用私人资料首次测试。

## A · 工程完整性（优先完成）

| ID | 操作 | 期望结果 | 反馈重点 |
|---|---|---|---|
| A01 | 运行 `python -m unittest discover -s tests -v` | 全部测试通过 | Python、SQLite、OS 版本 |
| A02 | 用 `examples/sample_dialogue.md` 导入两次 | 第二次 created=0，候选不重复 | 幂等性是否直观 |
| A03 | 导入 `examples/chatgpt_sample.json` | 根据 current_node 只得到当前分支消息 | 分支遗漏是否透明 |
| A04 | 导入包含一个错误文件的目录 | 其他文件继续入库、坏文件有显式错误 | 错误定位是否容易 |
| A05 | `bridge export` 生成 Vault 并在 Obsidian 打开入口 | 普通 Markdown + 链接显示 | Properties、中文标题、链接表现 |
| A06 | 通过 `candidate approve` 批准一条 Idea | 正式对象出现，原 Candidate 已决议 | 审核流程是否繁琐 |
| A07 | 编辑对象正文；先 `bridge pull`，再 `--apply` | preview 不修改 SQLite；apply 增加 revision，正文更新 | 是否需要可视化 Diff |
| A08 | 故意改 `vkf_revision` / 关系区 / 文件名 | 报冲突，不静默改写数据 | 错误提示是否明确 |
| A09 | 一边修改 SQLite 一边在 Obsidian 改同一笔记 | 检出版本冲突，不覆盖双方 | 冲突解决需求 |
| A10 | 运行 `backup`、`doctor` 并重新加载 | 所有对象与对话仍可查询，doctor.ok=true | 恢复操作是否清晰 |

## B · 真实历史导入（推荐使用匿名化样本）

从自己的历史中取三组内容：简短对话、长篇技术讨论、具有多个不同分支/格式的对话。测试 `.json` 和 `.md`：

- B01：导入后按 turn 查看消息有没有错位、重复、代码块断裂、角色误判。
- B02：图片、文件、公式、代码和引用是否保留为可接受的文本；记录被跳过的资源。
- B03：反复导入同一批聊天，检查 `created_conversations` / `duplicates` / `conflicts` 是否合理。
- B04：对一份导出更新后再导入，确认系统没有覆盖你已批准的观点。
- B05：对于含上百条消息的长聊天，观察 Obsidian 中是否仍能浏览和检索。

**建议记录的数据（真实计数，以命令输出为准）**：输入文件数量、解析成功数量、总消息数、跳过分支/附件数量、重复数、错误数、手工纠正耗时。

## C · 认知模型反馈（最重要）

选取数段你真的觉得有启发的 AI 对话，先用 `--extract heuristic`，然后可选用 `--extract llm` 对同一段对话提炼（需要你同意将该对话发送给相应模型）。

- C01：人工判断 Candidate 中真正值得保存的比例（precision-like），按 Knowledge / Idea / Question 分开记录。
- C02：人工找出被遗漏的有价值思想，记录是因为格式、模型提炼、去重还是结构限制。
- C03：拒绝、批准、合并候选的过程，是否比直接在 Obsidian 写一条笔记更费力？
- C04：一个 Idea 逐渐演化为 Understanding 时，当前的“新建 Understanding + 关系连接”方式是否符合直觉？
- C05：从一条新 Knowledge 建立 `raises` 或 `analogous_to` 的关系，Graph 和 Sources 是否足够有意义？
- C06：一个开放 Question 在 Base / Graph / Markdown 列表中的可见性是否足够？

### 人工定量表（每组选取相同样本）

| 指标 | 离线规则 | LLM 模式 | 说明 |
|---|---|---|---|
| 候选数量 |  |  | 越多不代表越好 |
| 你愿意批准的数量 |  |  | 用户判断为准 |
| 候选重复数 |  |  | 跨轮次与跨对话重复 |
| 明显错误/张冠李戴数 |  |  | 包括 AI 内容被误认为你的观点 |
| 人工整理用时 |  |  | 包含候选审核时间 |
| 你自己发现的新联系数 |  |  | 与普通笔记方法对比 |

## D · 如何提交反馈

完成 A01–A08 后即使发现问题也可以反馈，不必完成所有项目。可以将已填的 `FEEDBACK_TEMPLATE.md` 或精简后的问题描述发回对话。

若命令出错：提供**执行命令（隐藏密钥和本地私人路径）、Python/SQLite 版本、exit code、JSON 错误输出、匿名化最小输入**。不要分享完整私人聊天或 API 密钥。
