# V1 代码教学与验证

## 1. 链接和业务目标

为什么需要：用户给的是 URL，工具接受的是 repository + issue_number。必须在模型参与前判断允许范围。

位置：`app/schemas.py::parse_issue_url`；`app/api.py::POST /analyze`。

当前代码只接受 HTTPS 的 github.com，以及 `/owner/repo/issues/正整数` 路径。PR 链接直接报错；URL 中的 query、端口、用户名和仿冒域名被拒绝。允许普通评论 fragment，但忽略它并重建规范 Issue URL。仓库名可大小写不同，返回配置中的规范拼写。

验证：test_validation.py 覆盖仿冒域名、PR、越界仓库、非法编号、参数类型和额外字段；test_api.py 验证HTTP状态。还必须检查 GitHub 返回的 pull_request 字段，避免用户把 PR 编号写进 `/issues/` URL；test_github.py 已覆盖。

限制：不支持 GitHub Enterprise、多仓库、GitHub 短链接或 query。它们不属于 V1 场景。

## 2. MCP 在这份代码中做什么

为什么需要：把可调用能力与模型交互分开，同时使用 SDK 完成协议通信。

位置：`mcp_server/server.py::create_server` 与 `app/mcp_client.py::connect_tools`。

服务端注册两个普通 async Python 函数。客户端通过 sys.executable 启动 `python -m mcp_server.server` 子进程，再执行 `initialize → list_tools → call_tool`。stdio 的 stdin/stdout 承载协议，日志留在 stderr。HTTP 请求还是由 `GitHubReader` 执行，MCP 不负责访问 GitHub，也不替我们判断权限。

例如模型要求读取评论第2页时，应用先检查第1页是否给出 next_page=2，再调用 MCP；服务端还用 Pydantic 检查 page<=2，并再次检查仓库白名单。工具的 readOnlyHint 是提示，实际只读边界来自代码中没有写入端点。

实际问题：普通 dict 返回在该 SDK 版本下可能没有 structuredContent。客户端优先取 structuredContent，否则读取单条 TextContent 并解析 JSON。不是所有文本都直接传给模型；对象类型、字节数和 ok 状态仍要检查。

验证：test_mcp_integration.py 实际创建子进程，测试工具发现、调用、参数 schema、白名单、两页读取、取消与超时。scripts.demo 执行同样的通信过程，但外部 HTTP 和模型使用测试替身。

限制：每个请求新建 MCP 进程，启动有开销；V1 优先保证生命周期简单，不宣称吞吐量。连接参数与启动模块由应用代码指定，模型不能启动任意命令。

## 3. GitHub 数据与读取边界

为什么需要：公开 API 仍会限流、超时、返回 PR 或异常结构，评论可能很多。

位置：`mcp_server/github.py::request/get_issue/list_comments`。

URL 由固定 api.github.com + 配置仓库 + 校验后的数字编号构建；不跟随跳转、正文中的链接或 Link 头中的任意地址。先检查仓库 private=false。状态错误、连接失败、非法JSON和大小超限被转为安全的错误码，原始异常和凭证不返回。

`list_comments(page=1)` 固定 per_page=10；可能有更多时返回 next_page=2。第二页不再允许继续，若可能仍有更多则 limit_reached=true。应用最多获得前20条评论，并拒绝重复页。正文截断标志会变成响应 warnings。评论数来自 Issue 读取时的快照，不能保证并发编辑时恰好一致。

实际问题：最初 trust_env=False 导致当前环境无法联网。独立 HTTP 测试显示开启环境代理可访问 GitHub，于是服务端支持受信任代理环境变量，客户端显式注入这些变量。没有改变允许仓库、接口或 TLS 校验。

验证：test_github.py 覆盖404、401/403/429/451、500、重定向、网络超时、结构、正文截断、分页和响应上限。最初真实检查返回github_not_found，后续用户创建Issue #1后，真实读取成功，评论返回空列表；历史与新结果均保留。故障场景为用户的模拟案例，没有声称复现了真实缺陷。

## 4. 真实工具调用循环

为什么需要：一次模型请求只产生调用提议；要获得基于工具结果的答案，必须执行并把结果交还模型。

位置：`app/engine.py::tool_loop/execute_call/ask_model`。

循环过程：

```text
模型返回 assistant.tool_calls
→ 对每个调用检查名称、JSON参数、目标、顺序和重复页
→ session.call_tool（真实 MCP）
→ 追加 role=tool、tool_call_id=模型调用ID、content=JSON结果
→ 再请求模型
→ 模型停止工具调用后，单独请求最终JSON
```

工具选择确实来自模型。程序没有提前固定执行两个工具，也不伪造 assistant 调用。它只检查完成条件：必须成功读过 Issue 与第1页评论，才能生成分析。模型不调用必要工具就返回 model_skipped_tools。

被拒绝的工具请求也占6次预算；模型每次请求占8次预算。同时限制消息字节数。每次请求使用独立 runner 和消息列表，不复用聊天历史。一个模型响应可以有多个工具调用，当前逐个执行以保留顺序，不增加并行复杂度。

验证：test_engine.py 检查调用ID回填、多个调用、非法JSON修正、越界、未知写入工具、重复读取、跳过工具和预算停止；test_llm.py 使用实际官方 SDK + 模拟 HTTP 请求验证 wire 格式及关闭自动重试。

限制：没有自主规划、跨请求会话、缓存或暂停恢复；无需 LangGraph。字节预算不是 tokenizer，V1 通过返回大小和 max_tokens 作保守限制，实际 token 用量以模型接口为准。

## 5. 最终结构化结果和证据范围

为什么需要：界面和测试需要稳定字段；合法JSON也可能缺字段、类型错误或包含多余字段。

位置：`app/schemas.py::Analysis`；`app/engine.py::generate_analysis`；`app/llm.py::complete`。

最终请求启用 json_object，并提供 JSON schema、格式示例和读取限制。结果必须通过严格 Pydantic 校验，包含五个必需字段；分类有枚举。失败后只重试生成一次，不把非法结果反复拼回上下文。输出截断或没有候选也会失败。程序始终返回 documentation_checked=false 和 V1 范围提示。

验证：结构缺失、修复成功、两次非法结果、截断等已覆盖。自己的单个测试Issue已做两轮真实模型人工核对，分类和关键事实有来源支持；首轮发现文案问题后调整提示词，第二轮仍有追问偏多的限制。详见validation.md，不能以这个开发案例代表独立效果。Pydantic只能验证结构，不能证明草稿正确；“无文档”提示也不能自动消除所有幻觉。

## 6. 超时、取消和有限的请求状态

为什么需要：单次网络 timeout 不等于整个流程时间预算；客户端离开后也不能继续消耗模型请求。

位置：`app/engine.py::run/fail`；`app/api.py::analyze`。

asyncio.timeout 包围模型创建、MCP启动、读取循环和最终生成。API把整个 runner 放在一个 worker task 内，使 MCP 的异步上下文始终由同一个 task 进入和退出。检测断连后取消 worker；取消/超时清理会话后保留明确状态，失败分析置空。

当前 task_id 是单次请求ID，response 是本次业务结果；messages 是模型上下文，两者不是同一份状态。它们均未持久化。并发隔离测试检查了不同请求内容没有进入对方消息列表，但这不代表已完成 V3 的会话状态功能。

验证：慢模型、工具执行中取消、真实 MCP 初始化后取消及整个任务超时均通过。HTTP已断开的客户端无法收到取消JSON；服务记录取消，命令行可返回取消结果。清理耗时不纳入虚构的严格墙钟性能承诺。
