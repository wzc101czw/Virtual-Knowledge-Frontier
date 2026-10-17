# VKF v0.3.1 — Research Map 超时定位与断点恢复

## 原因与修复边界

在 v0.3.0 中，Research Mapping 对每个不超过约 13,000 字符的完整对话分块串行调用 Chat Completions，再对多个分块进行全局研究结构整合。每次请求沿用全局 `timeout=60` 默认值；模型需要较长推理时间、网关变慢、SSL/TCP 网络阻塞时可能抛出 `TimeoutError`。原版只在**全部请求完成**时保存 Research Map，因此一个晚期分块超时导致本轮之前成功的分块需要重复调用。

`transport stage: TimeoutError` **不能证明**原因究竟是运营商网络、代理还是推理延迟。`urlopen(timeout=...)` 使用底层阻塞网络操作的 timeout，不代表整条流水线严格受一个总时钟约束。该问题与模型返回无效 JSON 不是同一种错误。

v0.3.1 修复：

1. 新增可单独保存的 `research_timeout`（默认 **300 秒**，最大 1200 秒），不改变短任务的默认 60 秒；CLI `--timeout` 优先。
2. 可以通过 `config set research-chunk-chars 6500` 或 `research map --chunk-chars 6500` 调低单次模型输入字符上限（默认 13000）；减少单次推理负载，但请求次数可能增加，跨分块观点更依赖全局综合。
3. 每个成功且经过证据校验的**局部 Research Fragment**立即保存到 SQLite v8 的 `research_map_checkpoints`，全局整合成功并校验后亦可形成检查点。
4. 失败后再次使用**相同模型、同一 API Base、同一原文及相同 JSON/Token 请求设置**运行，自动复用未受影响的分块。成功生成并保存正式 Research Map 后自动清理对应检查点。
5. 新增错误上下文（第几块、已完成块数、请求阶段、具体 timeout 设置），不会把原始提示词、模型正文或 API Key 放入错误日志。
6. 网络超时默认**不自动重试**，因为上游可能已经处理并计费；用户可自行重试未完成分块。
7. 生命周期 `derived` / `conversation` / `all` 操作会在备份与事务中清除其关联的检查点。

**注意：从 v0.3.0 升级后，不能恢复它在升级前失败的那次 Research Mapping 请求；因为旧版没有持久化分块结果。断点恢复仅对 v0.3.1 开始的请求生效。**

## Windows PowerShell 操作

备份数据库、Vault；在 v0.3.1 源码目录下使用原来的数据库文件，执行：

```powershell
$DB = "D:\VKFData\vkf.db"
$CONV = "conv_你的研究对话ID"

python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor

python -m vkf_storage --db $DB config show
python -m vkf_storage --db $DB config set research-timeout 300
# 若 API 网关对复杂/长输入持续超时，可额外减小单次请求（这会增加调用次数）
# python -m vkf_storage --db $DB config set research-chunk-chars 6500

# 如有需要可用一次性 --timeout 480 覆盖持久配置
python -m vkf_storage --db $DB research map $CONV --mode llm --progress
```

运行过程中 `--progress` 会在 **stderr** 输出当前块的序号、是否复用检查点、是否正在请求模型和本次 timeout。stdout 仍保留机器可读 JSON 输出。它不会输出私人对话内容。

如果中途失败，检查保存进度：

```powershell
python -m vkf_storage --db $DB research map-progress $CONV
```

例如，`total_fragments=5`，`completed_fragment_numbers=[1,2,3]` 表示已有三块完整通过校验并保留。再次执行同样的 `research map`，将只补做其余块及最后全局综合。若错误发生在最后全局综合阶段，局部块也会保留。

若改变 `research-chunk-chars` 或 `--chunk-chars`，输入分块边界也可能改变，因此先前的检查点不一定能够复用。

只有当你**明确希望放弃此前成功的局部结果，全部重新调用模型**时才使用：

```powershell
python -m vkf_storage --db $DB research map $CONV --mode llm --progress --restart
```

`--restart` 会清除该 **conversation + model** 的所有未完成 Research Mapping 检查点，包括同模型不同兼容参数下的缓存；不会删除原始聊天，不会重新计算已存在且完整保存的 Research Map。如果映射已经完成，应在现有 Map 上进行 `research revise` 而不是盲目重跑。

## 如何判断依然超时的原因

错误增加：`phase=connect_or_headers`（连接/TLS/等待响应头阶段）或 `phase=response_body`（读取响应正文阶段），以及 `timeout_seconds` 与 `elapsed_seconds`。这仍只能确定网络调用的失败阶段，不能确定服务商处理进度。

若简单的 `model-probe --task research --timeout 300` 通过，但真实长对话仍超时，优先怀疑**输入长度、推理时间、网关上限或响应体传输**。每次研究分块接近 13k 字符，实际可能有多个分块和一次全局整合；探针只发送简短合成研究内容，因此不能代替长请求负载测试。

如仍失败，请提供以下**脱敏**信息：运行命令（可替换数据库路径）、出错片段序号与总数、`phase`/`timeout_seconds`/`elapsed_seconds`、模型名称和 API 服务提供商，以及 `research map-progress` 输出。不要提供 API Key 或私人对话原文。

## 数据安全与兼容性

- SQLite Schema **v7 → v8** 迁移在已有 v7 数据库上创建 `*.pre-v8.*.db` 备份；不会更改原始对话、已保存的 Research Map、Candidate 或人工评价。
- Checkpoint JSON 包含尚未审核的模型提炼结果，是**私密认知数据**。请像保护 `vkf.db` 一样保护数据库和迁移备份；不要把它们放入公共仓库。
- 如果修改模型、API Base、Prompt 或 JSON/Token 兼容配置，旧分块默认不会被误用，新的请求可能需要重新计费。
- 有些代理存在独立的请求总时长上限，提高本地 timeout 并不能突破它。
- 目前不提供跨进程的“恰好一次模型调用”保证；同一数据库不建议同时运行多份相同 Research Map。
- v0.3.1 未连接任何真实 GPT6-Astra 提供商进行测试；重试逻辑由离线模拟失败验证。
