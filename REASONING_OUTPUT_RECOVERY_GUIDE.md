# VKF v0.3.3 — 推理标签 / JSON 输出协议恢复指南

本版对 v0.3.2 的 **Chat Completions 兼容网关输出**作了保守的改进，**不更新 SQLite Schema（仍为 v8）**，不修改 `MAPPING_PROMPT`，不改变自动审批策略。

## 1. 为什么之前 `content_shape=reasoning_tag`？

收到 HTTP 200 只能说明服务器返回了完整 HTTP 响应。返回消息 `choices[0].message.content` 以 `<think>`、`<analysis>` 开头，说明**最终答案文本与推理标记混在了同一个字符串**，或模型最终只输出了推理文本。即使发送 `response_format={"type":"json_object"}`，部分第三方 OpenAI 兼容 API 也可能不完全遵守它。

`output_tokens=10055` 高于传入 `max_tokens=6000` 代表**提供商报告的实际消耗超过请求中声明的额度**，可能是参数忽略、代理换算、token 统计口径差异。不能仅根据这一项确定原因，也无法由 VKF 客户端强制服务端正确计费或限制输出。`finish_reason=stop` 并不意味着响应是合法 JSON。

**安全处理原则**：
- `<think>...</think>\n{"...":...}`（闭合标签 + 完整合法 JSON）→ 可以只解析后面的最终 JSON；
- `<think>...</think>\n```json\n{...}\n``` `（闭合标签 + 完整 JSON 代码块）→ 可以解析最终 JSON；
- `<think>...`（标签未闭合）或 `<think>{"...":...}</think>`（只含推理）→ 明确拒绝；
- `<think>...</think>\n普通自然语言` → 明确拒绝；
- `message.reasoning_content` 为独立字段、`message.content` 为合法 JSON → 仅解析最终 `content`；
- `message.content` 为列表 → 过滤明确标记为 reasoning/analysis/thinking 的区段，不将其当作最终答案。

**我们没有读取你这次实际的 19,045 字符模型正文**。上传的 `vkf.db` 只保留故障文本的诊断元数据，没有完整回复内容。所以不能保证新解析规则一定适合本次返回；这取决于推理标签后面是否有真正的最终 JSON。

## 2. 首次升级和最小重试（Windows PowerShell）

1. 备份你的 `vkf.db` 和 Vault（建议 `python -m vkf_storage --db $DB backup "..."`）。
2. 解压完整 v0.3.3 包或从 v0.3.2 应用补丁（`git apply`），在新工程目录运行：

```powershell
$DB = "D:\VKFData\vkf.db"       # 更换为真实路径
$CONV = "conv_你的具身智能对话ID"
python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor
python -m vkf_storage --db $DB research map-progress $CONV
```

当前上传的数据库没有成功 Research Mapping 检查点；此前失败的是 **fragment 1/5**，不是 2/5。第一次重试可直接定点减小其负载并避免再次请求已知失败的整块：

```powershell
$env:VKF_CHAT_JSON_RETRIES = "0"     # 可选，定位阶段避免付费重复请求
python -m vkf_storage --db $DB research map $CONV --mode llm --progress --split-fragment 1
```

如果已有新的成功检查点，它们会根据相同的源内容、Prompt、模型、API Base 和输出配置恢复；**不要执行 `--restart`**。仅增加超时时间不会解决推理标签导致的 JSON 解析错误。

## 3. 如果仍然得到 `reasoning_prefix=unclosed` 或 `closed_without_final`

先尝试仅使用合成数据进行 `research` 格式探针，不发送真实对话：

```powershell
$env:VKF_CHAT_JSON_MODE = "json_schema"
python -m vkf_storage --db $DB model-probe --task research --max-tokens 3500
```

如果 API 返回 400，说明这条接口可能不支持此参数；将环境变量恢复 `json_object`，不要持续重复有相同错误的请求。

如果 provider 明确支持 Chat Completions 推理控制，可以按需测试：

```powershell
$env:VKF_CHAT_TOKEN_FIELD = "max_completion_tokens"
$env:VKF_CHAT_OMIT_TEMPERATURE = "1"
$env:VKF_CHAT_REASONING_EFFORT = "low"   # 新增；可留空禁用
python -m vkf_storage --db $DB model-probe --task research --max-tokens 3500
```

重要：这三个可选参数**不保证任何第三方服务商支持**；出现 400 应根据错误指示回退。`reasoning_effort` 没有默认值。修改 JSON Mode、token 字段或推理强度会改变**新请求的检查点指纹**，因此可能无法复用采用另一套请求参数创建的缓存。基础模型配置仍由现有 `config` 管理，以上兼容变量仅影响当前 PowerShell 进程。

## 4. 最小且隐私安全的诊断

v0.3.3 在不泄露正文的前提下提供：
- `content_shape=reasoning_tag`：输出起点是推理标签；
- `reasoning_prefix=closed`：完整推理区段已闭合，但最终 JSON 解析仍失败；
- `reasoning_prefix=unclosed`：推理区段没有正常结束；
- `reasoning_prefix=closed_without_final`：只有推理，没有最终答案；
- `final_shape=...`：推理区段结束后内容的形态（对象、代码块或普通文字）；
- `separate_reasoning=true/false`：服务商是否另行提供推理字段。

如果需要在本机检查未经处理的回复，可以**主动**设置 `VKF_CHAT_DEBUG_DIR` 为 Vault 和 Git 仓库之外的目录。VKF 只在启用时保存无效模型回复，绝不在错误日志中直接显示内容。文件可能包含你的私人研究材料；**不要上传未脱敏的完整文件或 API Key**。

## 5. 验收

- 只有完整、合法、具有正确 JSON 结构的最终回复能够进入 `validate_plan`；
- 未闭合/只有推理/只有普通文字时不会创建研究提案或正式 Understanding；
- 可复用成功检查点，不破坏原始对话；
- JSON 解析成功后仍须由人类研究员检验提炼是否过粗、过碎或遗漏研究问题。

本版所有网络/API 相关测试使用模拟响应。**未对你的实时 gpt-6-astra 服务发起请求。**
