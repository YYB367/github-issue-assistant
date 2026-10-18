# GitHub Issue 分析与处理助手 — V1

给一个允许仓库的 Issue 链接，模型选择只读 MCP 工具，应用校验并执行，随后返回问题摘要、分类、已知信息、待补充信息和初步回复草稿。返回中包含真实工具调用轨迹、状态、耗时及模型报告的 token 用量。

V1 无知识库，不核对项目文档、不复现问题，也不发布评论或添加标签。处理建议只能作为待验证的初步草稿。已完成离线功能验证，并用自己的测试 Issue #1 跑通真实 MCP + DeepSeek 的 CLI 与 HTTP 流程；测试 Issue 的故障场景是模拟的，不代表已解决真实项目缺陷，见 [验证记录](validation.md)。

## 目录与阅读顺序

```text
app/
  config.py       环境变量与固定资源上限
  schemas.py      URL、工具参数、分析结果及响应模型
  mcp_client.py   官方 SDK 建立 stdio 会话、发现和调用工具
  llm.py          官方 OpenAI SDK 调用 DeepSeek 兼容接口
  engine.py       模型 → 参数校验 → MCP → 结果回填 → 结构化输出
  api.py          POST /analyze、GET /health；/docs 是 V1 操作界面
  cli.py          命令行真实分析
mcp_server/
  github.py       固定 GitHub API、公开仓库检查、分页和大小限制
  server.py       注册 get_issue、list_issue_comments
scripts/
  demo.py         无密钥离线演示：真实 MCP，模拟 GitHub/模型
  check_mcp.py    只读真实 GitHub 验证，不调用模型
tests/            单元、HTTP、SDK 请求格式和真实 stdio 集成测试
docs/             教学、参考审查、开发记录及独立案例集
requirements.in  直接依赖的版本
requirements.lock 所有已安装依赖的精确版本
```

## 安装

实际验证环境为 Windows、Python 3.12.6。建议使用 Python 3.12；Linux 尚未验证。MCP 使用官方 SDK 的维护分支 `1.30.0`，不混用 v2 导入路径。OpenAI SDK `3.19.2` 使用 HTTPX2；GitHub 和 MCP 使用 HTTPX 0.28.1，两者可共存，已安装并检查。

在项目目录执行 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
```

若当前电脑 Python 不在 PATH，可将第一行改为：

```powershell
& 'D:\python\python.exe' -m venv .venv
```

不需要 Node.js、Chroma、SQLite、LangChain 或 LangGraph。pytest 是开发验证依赖；未拆分生产与开发锁文件，以保持 V1 安装简单。

## 配置

若没有 `.env`，复制 `.env.example`；当前工作区已经创建了空密钥的 `.env`。不要覆盖已经填好的配置：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 填写：

```dotenv
ALLOWED_REPOSITORY=YYB367/learning-mcp-server
DEEPSEEK_API_KEY=你的本机密钥
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
GITHUB_TOKEN=
```

模型名称和接口地址来自配置，上面的模型名来自官方文档示例。本机配置已用 deepseek-flash 完成两轮真实分析；其他账号或服务是否支持该名称需实际核对。V1 显式使用非思考模式；不支持需要保留 reasoning history 的思考模式工具循环。兼容服务若不支持 `thinking` 参数，需要在 `app/llm.py` 对照其文档调整。

GitHub token 可为空；若填写，使用限定仓库的只读凭证。程序还检查该仓库为公开仓库。密钥不进入模型消息、工具结果或日志；GitHub token 只注入 MCP 子进程。`.env` 已被 gitignore 排除。

程序支持受信任的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 环境变量，并将它们传入 MCP 子进程。此环境需要代理才能访问 GitHub；代理地址由运行环境配置，模型不能指定。没有关闭 TLS 验证。

## 先做不消耗密钥的演示

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.demo
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

演示使用固定的模拟 Issue #1 和 11 条评论，运行真实 stdio MCP 子进程；返回 `mode=offline_demo`。模型也是预设测试替身，不是 DeepSeek。预期看到 `get_issue`、评论第1页、评论第2页三个成功轨迹，以及五项结构化分析。模拟 #1 与真实 GitHub #1 无关联。

## 真实运行与演示

在自己的 `YYB367/learning-mcp-server` 仓库创建一个安装类测试 Issue，并记录实际编号；不要假设 #1 存在。创建内容的示例在 [测试 Issue 模板](test-issue-template.md)。本项目不会替你创建或修改 GitHub 内容。

当前用户已创建 [测试 Issue #1](https://github.com/YYB367/learning-mcp-server/issues/1)。2026-10-12 的 CLI 和 HTTP 验收均成功；当时评论数为0。当前工作区已启动新的演示服务：[http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)（原8000端口已被占用，没有停止原服务）。此地址只在本机该进程仍运行时可用；一般启动步骤仍使用下方命令。

先验证 GitHub/MCP：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_mcp 'https://github.com/YYB367/learning-mcp-server/issues/实际编号'
```

再启动 HTTP 服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000 --log-level info
```

打开 [Swagger 操作界面](http://127.0.0.1:8000/docs)，选 `POST /analyze` → Try it out → 填入下面对象 → Execute：

```json
{"issue_url":"https://github.com/YYB367/learning-mcp-server/issues/实际编号"}
```

先检查 `status`、`error`，成功时再阅读 `analysis` 和 `tool_trace`。V1 的轨迹在请求完成后返回，没有实时进度页面。`GET /health` 仅检查本地 HTTP 响应和配置是否有密钥，不证明外部服务可用。更改 `.env` 后重启服务。

也可直接运行真实模型分析，并保存人工评估用的结果：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.cli 'https://github.com/YYB367/learning-mcp-server/issues/实际编号'
```

CLI 返回 JSON，成功退出码为 0，失败为 1。Ctrl+C 可取消任务；HTTP 客户端断开会取消后台工作并清理 MCP 子进程。已断开的连接无法再收到取消响应；服务记录 cancelled，CLI 可返回取消状态。

## 输出与错误

`analysis` 包含 `summary`、`category`、`known_information`、`missing_information`、`reply_draft`。分类枚举是 installation/dependency/configuration/other/unclear。响应另有 `task_id`、`status`、`error`、`tool_trace`、`warnings`、`model_calls`、`usage`、`documentation_checked=false`。

| HTTP | 典型情况 | 结果 |
|---|---|---|
| 200 | 完成 | completed + analysis |
| 400 | 不合法链接、PR | failed + 明确错误 |
| 403 | 非允许仓库 | repository_not_allowed |
| 404 | GitHub 未找到资源 | github_not_found（也可能无权访问） |
| 422 | HTTP 请求结构错误 | FastAPI 参数校验错误 |
| 503 | 没配置模型密钥 | model_not_configured |
| 504 | 单次模型/GitHub超时或任务超时 | timed_out |
| 502 | 上游访问受限、连接失败、非法模型结果等 | failed |
| 499 | 任务取消 | cancelled（断开的客户端无法接收） |

失败不会返回部分分析作为成功结果；已经发生的工具轨迹会保留。模型输出不合法时只修复一次，仍受整个任务预算限制。模型拒绝调用必要工具时返回 model_skipped_tools，程序不会伪造模型工具调用。

## 边界与已知限制

默认最多 6 次工具调用（包含被拒绝的调用）、8 次模型请求、90 秒任务预算。GitHub 单次 I/O 超时 10 秒，模型单次请求预算 30 秒，SDK 自动重试关闭。MCP 会话单次读响应预算 30 秒；清理可能增加少量墙钟时间。

评论每页 10 条，仅允许第1、2页，共最多20条；第2页需要第1页返回 next_page。应用拒绝重复读取。正文最多6000字符、单条评论1200字符、标签20个；截断会提示。HTTP响应最多512000字节，工具结果最多24000字节，提交给模型的消息与工具定义总大小最多100000字节，模型每次输出最多2200 tokens。字符和字节上限不是精确 token 数，也不保证任何模型的上下文容量；模型用量取实际接口返回值。

每次请求独立创建 runner、消息列表和 MCP 会话，`task_id` 只用于关联本次结果和日志，尚无持久化、恢复、多轮或全局并发限流。服务应绑定本机；V1 没有部署鉴权。外部内容中的诱导指令被当作数据，程序阻止越界工具，但模型是否会产生误导性自然语言仍需人工真实评估。

详细说明见 [代码教学](teaching.md)、[开发记录](development-log.md)、[验证记录](validation.md)。下一版建议仅是 V2 文档知识库；收到用户指令后再进入 V2。
