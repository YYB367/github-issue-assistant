# V5 代码教学

## 为什么页面只负责展示和提交

`app/static/app.js` 的 `api` 调用同源HTTP；创建会话后用任务ID轮询，每次任务有90秒默认预算，页面最多自动刷新180次。任务完成显示真实 `tool_trace`，没有把“读取成功”装作模型决定。页面刷新从sessionStorage恢复会话ID，完整状态仍由 `StateStore.get` 从SQLite读取。最近列表只取有限摘要，业务状态没有放进浏览器历史消息。

`start` 在发送前保存request_key和revision，连接断开后保留原请求身份。`refresh` 从服务器重读任务；请求不明确时界面提示先刷新。服务已接收的分析继续在后台运行；取消要调用cancel接口。用户取消与后台结果竞争仍由V3的 `finish` 状态检查保证，迟到结果不会覆盖取消状态。

## 为什么确认不能只放在按钮上

`showOp` 展示仓库、Issue、完整payload、操作ID、hash和失效时间。界面要求勾选并输入 `confirmation_text`，尚未保存的改稿会清除勾选并禁用执行。真正安全边界仍是 `OperationStore.confirm / claim`：检查内容hash、来源revision、允许仓库、过期和当前状态。绕过按钮直接发HTTP，也必须通过这些校验。

修改草稿、补充信息或重新分析会使旧操作失效。后台执行中不允许通过编辑撤回已经发出的请求。unknown状态只显示只读核对，不显示确认重发；未找到继续unknown。明确401/403/429修正后仍需绑定失败次数重新确认，最多3次总发送，旧确认不能跨失败次数重放。这些规则来自V4，V5只增加可操作入口。

## 外部文本如何进入页面

`renderResult` 使用 `document.createElement` 和 `textContent` 展示建议、证据和参数；不使用innerHTML、不渲染远端HTML。模拟证据包含script标签，浏览器实际检查它只显示文本、没有生成script节点。外链只允许无凭证的HTTPS GitHub地址。根页面CSP仅允许本站脚本和样式；不为自动化测试放宽CSP。

外部数据即使写着“直接发布”，也不会触发页面按钮或确认接口；写入工具仍不在MCP/模型工具清单中。模型生成草稿不会自动建立授权。

## 如何理解当前计时

`AnalysisRunner.phase` 用perf_counter在finally累计耗时，所以模型失败、超时也保留已进入阶段的时间。`run`记录mcp_connect、tool_loop、retrieval、generation；`ask_model`跨所有调用累计model_total，execute_call累计tool_total。工具循环与生成内部都包含模型等待，因此这些值不能全部相加。elapsed_ms还包含资源关闭，不是简单阶段求和。

模型usage是接口成功返回时提供的prompt/completion/total_tokens之和，usage_reported_calls表示有用量数据的调用数。失败请求可能计费但无usage返回，因此不能把这个和当作完整账单或据此承诺成本。旧记录缺少字段时不编造0值。

`execute_operation`记录preflight、write、total，保存在原操作JSON。核对后仍保留原发送耗时；没有伪造核对等于再次发送。

## 健康检查与启动检查分别证明什么

`/health`表示HTTP服务存活；`/ready`检查本地SQLite、配置了模型key、知识库标记存在。它不读取全部模型权重、不校验实际key有效性、不访问GitHub。关闭知识库时不要求知识库文件。写入配置单独报告，不阻止只读分析。

`scripts.check.inspect`核对运行Python3.12和requirements.lock，按PEP508条件标记选择本平台依赖，做目录可写与SQLite quick_check。`scripts.serve`先检查本地运行条件，再由API lifespan持有FileLock。启动检查和启动有时间窗口，所以最终仍以锁获取为准。

SQLite连接上下文管理器只负责事务提交/回滚；它不会自动关闭连接。V5只读检查使用 `contextlib.closing` 显式关闭，这一点由浏览器临时库清理时发现并修正。

## 日志如何帮助定位且不暴露输入

`RequestTelemetryMiddleware`给每个HTTP请求生成ID，用 `scope.route.path` 记录 `/sessions/{sid}` 这样的模板，不记录实际路径和查询串。`EventLog.emit`只接收允许字段；异常仅记类型和安全错误码，不记str(error)、堆栈或HTTP头。校验错误响应也不返回Pydantic默认的input字段。

任务ID关联 analysis_finished 的状态、用量和阶段；操作ID关联 operation_finished 的状态、失败码与次数。JSON日志是运维记录，SQLite中的任务、草稿与操作才是可恢复业务状态。两者不能互相代替。

## 如何验证这些设计

`tests/test_v5.py`检查就绪差异、分页边界、日志敏感数据缺失、指标落库、静态路径与错误响应。`scripts.browser_smoke`以真实Chrome打开真实本地HTTP服务，模型/MCP/GitHub响应均为假数据，断言FakeGitHub的POST数。`scripts.live_check_v5`单独通过真实配置跑只读分析；浏览器拦截confirm/execute端点，避免验收脚本触发真实写入。

这些是开发回归与一次现场验收。它们没有替代V2独立模型评估集，没有证明安装方案正确或当前检索覆盖所有文档。
