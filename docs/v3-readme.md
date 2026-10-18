# GitHub Issue 分析与处理助手 — V3

V3 在 V2 的真实 MCP 工具循环和文档检索之上，增加 SQLite 会话、任务保存、补充信息、继续分析、人工修改草稿、取消与重启恢复。只读允许的公开仓库 YYB367/learning-mcp-server。

每次版本交付都会提供**修改文件、行为变化、验证结果和已知限制**。本次详见 [V3 修改清单](v3-changes.md)、[教学说明](v3-teaching.md)、[开发与验证记录](v3-validation.md)。V1、V2 源码包保留；历史说明在 docs/v1-readme.md 和 docs/v2-readme.md。

## 安装和启动

已验证 Windows / Python 3.12.6，内置 SQLite 3.45.3。V3 未新增第三方依赖，继续使用 requirements.lock；本次验证已有锁定环境，未重新做全新机器安装。

在此项目目录执行（Python 路径按本机修改）：

```powershell
& 'D:/python/python.exe' -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock
./.venv/Scripts/python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 .env 填写 DEEPSEEK_API_KEY、DEEPSEEK_MODEL、DEEPSEEK_BASE_URL。已有 .env 无需覆盖。GitHub token 可为空（仍受公开 API 限流）。V2 已准备的知识库可直接复用；新环境执行：

```powershell
./.venv/Scripts/python.exe -X utf8 -m scripts.kb prepare-model
./.venv/Scripts/python.exe -X utf8 -m scripts.kb sync-docs
# 可选：有限历史报告，不作为已验证答案
./.venv/Scripts/python.exe -X utf8 -m scripts.kb sync-history --limit 20
./.venv/Scripts/python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8003
```

默认数据库为项目 work/sessions.sqlite3，可用 STATE_DB_PATH 改成绝对路径。只支持单进程、单本地用户：不要添加 --workers；同一数据库有进程锁，第二个实例启动失败。没有账户认证，session_id 是定位符而非访问凭证，服务应绑定 127.0.0.1。源码包不包含 .env、数据库、模型或缓存。

## Swagger 手动演示

打开 [V3 操作界面](http://127.0.0.1:8003/docs)，确认 /health 的 version=0.3.0。旧的 8000/8001/8002 服务可能仍在运行。

1. POST /sessions 创建会话：

```json
{"issue_url":"https://github.com/YYB367/learning-mcp-server/issues/1","use_knowledge":true}
```

保存返回的 session_id 和 revision。每次编辑或任务状态变化都会增加 revision，后续操作从 GET /sessions/{sid} 取得最新值，不能固定写死。

2. POST /sessions/{sid}/tasks 发起分析：

```json
{"expected_revision":1,"request_key":"demo-first"}
```

返回 202 和 task_id。GET /sessions/{sid}/tasks/{tid} 查询，直到 status 从 running 变为 completed、failed、timed_out 或 cancelled；完整分析、MCP 轨迹、检索证据、用量在 result。HTTP 查询成功不意味着模型任务成功，务必看 status/error。运行期间关闭页面不会取消任务，可使用 POST /sessions/{sid}/tasks/{tid}/cancel 显式取消。

3. GET 会话取得最新 revision，POST /sessions/{sid}/supplements：

```json
{"expected_revision":3,"text":"模拟补充：PowerShell 提示 npm.ps1 因脚本执行策略无法加载，Node.js 22、npm 10。此处不是实际复现结果。"}
```

示例 revision=3 仅说明格式，请替换为实际值。最多12条、合计6000字符；单条最多3000字符，超限明确拒绝。请只填写脱敏信息。

4. PATCH /sessions/{sid}/draft 编辑草稿：

```json
{"expected_revision":4,"text":"谢谢反馈。请区分文档建议与实际运行结果，并尽量简短。"}
```

人工修改只更新当前 draft；latest_result 保存最近一次成功模型分析原文，旧任务结果也保留。draft_source=user 表示人工编辑。修改草稿不会调用模型，也不会发布到 GitHub。

5. 使用最新 revision 和新 request_key 再 POST tasks。继续分析会参考补充信息、上一轮摘要和当前草稿，重新读取 Issue、检索证据，并以新分析更新当前草稿。需要保留人工最终措辞时，在分析完成后再编辑。相同 request_key 和相同 expected_revision 重发会返回同一个任务；相同键配不同版本返回409。

6. 重启服务后 GET 原 session_id，查看保存的草稿、证据、补充信息及 task_ids。若重启前任务未完成，会被标记 failed/server_interrupted，用户用新请求键显式重试；不会自动重复调用模型。

## 一条命令演示两轮

下列命令读取真实测试 Issue、调用真实 DeepSeek（使用模型额度），第二轮补充明确标为模拟，结果写入 verification/v3-live-http.json。再次执行会创建新会话并覆盖该报告，首次交付证据另存为 verification/v3-delivery-live-http.json。

```powershell
./.venv/Scripts/python.exe -X utf8 -m scripts.demo_v3
```

旧 POST /analyze 仍是单次、不保存业务会话的接口；CLI 行为同 V2。POST /knowledge/search 可独立检查检索，不调用模型。

## 范围、预算与验证

- SQLite 保存会话目标、补充、当前草稿、成功结果、任务快照及状态；聊天展示记录单独保存最近50条，**不会直接拼入模型消息**。
- 每轮只传补充信息、最多1000字符的上一轮摘要、当前草稿，另设24000 UTF-8字节上限。旧检索片段不重复带入，新证据保存在每次任务结果中。
- 单会话最多20次任务，V3 同时最多2个后台任务；单轮仍受90秒、6次工具、8次模型调用以及 V2 上下文预算限制。运行时编辑返回409。
- pending_operations=[]、operation_status=disabled_in_v3 明确保留业务字段；本版没有确认、发布、标签或其他 GitHub 写入执行器。
- 127项程序测试通过，真实两轮 HTTP 分析成功，进程重启后会话完全一致。12条 Chroma 弃用警告保留记录。详见验证文档，程序测试通过不代表模型答案正确。
- V2 的两处独立检索漏召回仍存在。本次真实模型能利用补充，但追问过多、重复确认已给版本、部分引用关联弱；未调参掩盖这些问题。
- 运行中只能查询任务状态，MCP 完整轨迹在结束后返回；没有实时流式进度。同步原生 Embedding 线程不能强制中断；取消后停止等待，原生调用可能继续至结束。
- 失败/取消保留上一轮成功分析与人工草稿；新的失败详情从对应 task 查询。服务退出/崩溃不能恢复模型内部执行位置，只恢复业务状态。

测试（--basetemp 指定新工作区临时目录，规避本机系统 Temp 权限问题）：

```powershell
./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/manual-test-temp
```

没有引入 LangGraph：当前分支用 Python 条件和 SQLite 短事务即可理解维护。下一版 V4 才实现具体操作确认与写入，等待用户指定。
