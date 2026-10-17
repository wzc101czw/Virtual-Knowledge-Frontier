# VKF v0.3.2：Research Mapping 的非法 JSON 与分块恢复

## 1. 本次故障属于“输出格式”，不是“连接超时”

示例错误：

```
research map failed at fragment 2/5; completed_checkpoints=1
model output stage: message.content is not valid JSON
length=14608, json_error=Expecting value, line=1, column=1
finish_reason=stop, output_tokens=7871, reasoning_tokens=2070, max_tokens=6000
json_attempts=2
```

`HTTP 200` 表示 Chat Completions 外层响应能够成功读取。`content_type=application/json` **只表示外层 API 响应**是 JSON，并不证明 `choices[0].message.content` 是合法 JSON。第一列报错不能说明模型一定返回了 `<think>`，也不能说明是 Markdown；必须观察回复形态或在明确同意后调试。

`finish_reason=stop` 不代表显式的长度截断。`output_tokens=7871` 大于请求所记录的 `max_tokens=6000` 值得排查服务商的请求参数执行、转接层行为、token 统计口径。不能据此猜测 API 接入商已经违约或 token 实际如何计算。

v0.3.1 原有重试实际上将**同一大段原文和同一输出预算再次发送**，只添加 JSON 格式要求。面对复杂内容，它可能重复失败。

## 2. 建议操作：只拆分已知失败的第 2 块

请先备份数据库；使用与之前完全相同的模型 ID、API Base、JSON Mode、Token Field 和 `research-chunk-chars`，否则已有成功检查点可能不匹配。**不要使用 `--restart`。**

```powershell
$DB = "D:\VKFData\vkf.db"
$CONV = "conv_实际对话ID"

python -m vkf_storage --db $DB init
python -m vkf_storage --db $DB doctor
python -m vkf_storage --db $DB research map-progress $CONV

# 直接跳过之前已知反复失败的大请求，对 fragment 2 细分后分别处理
python -m vkf_storage --db $DB research map $CONV --mode llm --progress --split-fragment 2
```

新的 `--split-fragment N`（N 从 1 开始）只在给定分块没有有效完整检查点时生效；其它成功分块继续从 v0.3.1 的检查点恢复。将待处理分块分为约 2～4 个更小的子分块，**每个子分块的消息 ID 和原文绝对字符范围保持不变**；结果先组合、校验，再作为完整原分块保存。若某个子分块再次失败，它之前的子分块也会持久化，下一次以相同参数重试只做缺失子分块。

你也可以在其他未知分块因非法 JSON 失败时显式开启有限的自动拆分：

```powershell
python -m vkf_storage --db $DB research map $CONV --mode llm --progress --split-on-json-error
```

自动拆分**不会递归无限进行**。上述两种模式均会增加模型调用和费用，不会默默默认启用。网络超时、鉴权失败、HTTP 4xx/5xx 不被当作 JSON 错误而触发拆分。

如果最终全局整合阶段返回无效 JSON，旧的局部检查点会保留；本版的自动拆分仅针对局部 Research Fragment，不负责全局整合。

## 3. 如果仍失败：不暴露敏感数据的诊断

v0.3.2 的 JSON 错误增加两个字段：

- `content_shape`：`object_prefix` / `array_prefix` / `markdown_fence` / `reasoning_tag` / `markup_prefix` / `markdown_heading` / `prose_or_other`。只描述回复开头形态，不输出正文。
- `requested_json_mode`：`json_object` / `json_schema` / `none`。报告 VKF 请求中的模式，而非宣称服务端遵守了该模式。
- `usage_check`：`provider_reported_completion_over_budget` / `within_or_unknown_budget`，仅用于排查兼容接口统计口径，不作为强制拒绝条件。
- `debug_capture`：默认 `disabled`，没有持久保存模型正文。

若你的 API 服务**明确支持 Chat Completions Strict Structured Outputs**，可以另行试验：

```powershell
$env:VKF_CHAT_JSON_MODE = "json_schema"
python -m vkf_storage --db $DB model-probe --task research --timeout 300
```

注意：更换 JSON Mode 会改变 checkpoint 匹配键；旧成功分块可能不复用。服务商若报 HTTP 400 `response_format` 参数不支持，请撤销该实验设置；不能假设所有兼容接口都提供严格 JSON Schema。

如只在本机诊断，并且**愿意把包含私人研究细节的模型回复写到本机**，可明确设置下述目录。VKF 不存储完整原始请求或 API 密钥，只保留非法 JSON 的 Assistant 回复文本；文件在 POSIX 系统上以 `0600` 权限创建，Windows 则依赖目标目录的 ACL，务必确保目录私有。请不要把它放入 Obsidian Vault、Git 仓库或云同步目录：

```powershell
$D = Join-Path $env:USERPROFILE "VKF-Private-Diagnostics"
New-Item -ItemType Directory -Force -Path $D | Out-Null
$env:VKF_CHAT_DEBUG_DIR = $D
python -m vkf_storage --db $DB research map $CONV --mode llm --progress --split-fragment 2
Remove-Item Env:\VKF_CHAT_DEBUG_DIR
```

错误日志只记录调试文件名。**不要上传未脱敏的调试文件**。可以自行检查文件中 `assistant_content` 的开头，归类是否为额外推理文本、Markdown、说明文字或语法不合法的 JSON；分享时仅提供脱敏片段。

## 4. 兼容、限制与认知质量

- v0.3.2 **不需要数据库迁移**，仍为 SQLite Schema v8；已有 `research_map_checkpoints` 保留。
- 不会自动批准 Knowledge、Idea、Understanding、Frontier 或正式研究空间。
- 从 v0.3.1 升级时不要改变此前的模型、原文、Prompt、分块大小和格式配置；之前成功的完整分块可被识别。
- 子分块越小，跨子分块思想越依赖最终综合。因此“JSON 解析成功”**不等于“人类认可提炼质量”**，仍应检查是否出现过分碎片化、概念重复或技术问题遗漏。
- 代码中的外部模型输出始终是未受信任数据；不会因为外部回复包含 JSON 字符串就自动将任意外围自然语言当作已验证认知信息。
- 该发布未调用真实 GPT6-Astra 兼容服务，第三方接口的输出差异仍需你的实际运行验证。
