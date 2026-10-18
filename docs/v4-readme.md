# GitHub Issue 分析与处理助手 — V4

V4 新增**添加已有标签、发布评论**，通过“预览完整内容 → 用户明确确认 → 程序检查与执行 → 保存结果”完成。评论发送后若超时或结果无法验证，标记 unknown，只能只读核对，不自动重发。

版本修改、原理和实际验证分别在 [修改清单](docs/v4-changes.md)、[教学说明](docs/v4-teaching.md)、[开发验证记录](docs/v4-validation.md)。以前版本源码包和独立评估记录保留。

## 安装与升级

仍使用 Python3.12、FastAPI、Pydantic、官方MCP客户端、Chroma和SQLite。没有新增第三方依赖；requirements.lock沿用已验证环境。

```powershell
& 'D:/python/python.exe' -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock
./.venv/Scripts/python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

本机用户已填写的.env不必覆盖。DeepSeek的接口、模型和密钥配置同V3；新机器的知识库准备步骤见[上版说明](docs/v3-readme.md)。

V4 默认使用 **work/sessions-v4.sqlite3**。升级时如需带入V3状态，先运行一次：

```powershell
./.venv/Scripts/python.exe -m scripts.migrate_v3_state
```

该命令用SQLite backup从work/sessions.sqlite3生成一致快照，目标已存在时拒绝覆盖；不停止旧服务，也不删除原数据库。当前工作区已迁移8个会话、7个任务，并核对原数据一致。之后V3/V4的数据各自独立，不自动同步。STATE_DB_PATH可覆盖V4目标位置；不要让两个服务共用同一数据库。

```powershell
./.venv/Scripts/python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8004
```

打开 [V4 Swagger](http://127.0.0.1:8004/docs)，health.version应为0.4.0。只支持本机单用户、单进程，不使用--workers。Host/Origin检查用于防止第三方网页触发本机修改，不是账户认证，勿直接公开部署。

## GitHub 凭证与写入开关

.env中设置 GITHUB_TOKEN；推荐仅选择自己的测试仓库 YYB367/learning-mcp-server，并授予Issues读写权限。程序额外要求登录账号拥有仓库push/maintain/admin权限，保守地拒绝只具备triage等其他角色的账号。仓库权限检查不能证明token的Issues写入scope，最终由GitHub接口校验。

GITHUB_WRITES_ENABLED默认false。准备执行时可改为true并重启，仍然必须逐操作确认；开关或token都不代替确认。密钥仅用于HTTP Authorization，不进入模型上下文和操作记录。用户输入本身会保存，填写前应脱敏。

## 操作步骤

先沿用V3创建会话、分析或编辑草稿。目标仓库与Issue创建后固定，另一个Issue用新会话。POST /sessions/{sid}/operations/preview只建立本地预览，当前草稿自动作为评论正文，不接受模型任意提供URL。

发布评论预览：

```json
{"expected_revision":2,"kind":"publish_comment"}
```

添加标签预览（先用GET /sessions/{sid}/available-labels查看已有标签）：

```json
{"expected_revision":2,"kind":"add_labels","labels":["question"]}
```

expected_revision请使用GET会话所得的实际版本。每次新预览会使同会话原预览/确认失效；若同时准备评论与标签，逐项执行，或使用两个会话。标签最多5个，不允许空列表，不创建/删除/替换标签。

完整审阅返回的 repository、issue_number、target_url、kind 和 **payload**。评论会附加唯一HTML注释标记用于核对，完整标记也在payload.body中显示并参与hash；它通常不会显示在GitHub渲染后的评论中，但实际正文含有它。

POST /sessions/{sid}/operations/{oid}/confirm，填写预览实际返回的两个字段：

```json
{"content_hash":"粘贴实际64位hash","confirmation_text":"粘贴实际完整确认文本"}
```

确认绑定目标、完整payload与来源会话版本，有效期为从预览创建起15分钟。改稿、补充或重新分析会失效；超时重新预览并确认。状态仍可能显示confirmed，但expires_at过期后执行必定拒绝。

POST /sessions/{sid}/operations/{oid}/execute，返回202后通过GET同一operation查询。执行时重新核对允许仓库、账号权限、公开/非归档仓库、真正的Issue、非锁定Issue以及所选标签存在。GitHub写入接口本身不向模型开放，MCP仍只有两个只读工具；两种写入由Python程序直接调用固定GitHub REST端点。

| status | 含义与后续 |
|---|---|
| previewed / confirmed | 待确认 / 已确认但尚未执行 |
| invalidated / cancelled | 内容状态变化 / 用户在发送前取消，不能再执行 |
| executing | 已被唯一执行者领取，不能编辑或取消来撤回网络写入 |
| succeeded | 返回内容已核验，结果含评论链接或标签 |
| failed | 明确失败或发送前失败，不能直接重发；401/403/429修正后可绑定失败次数显式重确认 |
| unknown | 可能已经写入成功，只允许核对，禁止重发 |

POST .../cancel仅取消previewed/confirmed。HTTP断开不撤回后台写入；重新查询操作记录。每次最多60秒、最多同时2个写任务，每个会话最多50条操作记录。

## 结果不明确时

POST /sessions/{sid}/operations/{oid}/reconcile，传 `{}`：评论最多扫描3页、每页100条，匹配完整正文、标记、账号ID和目标Issue；也可传 `{"comment_id":实际评论ID}` 定点核对。扫描时间从预览创建前1分钟起，避免毫秒与GitHub秒级时间的边界遗漏；不能消除所有时钟偏差。

找到匹配才改为succeeded；未找到仍为unknown，不意味着可以重发。标签通过GET检查目标标签是否已存在，只证明期望状态已达成，不证明一定由本次请求添加。同一Issue有executing/unknown操作时，其他新写入也被阻止。

若评论被编辑/删除、扫描超限或无法证明结果，V4保留unknown，**没有“忽略未知并强制重试”按钮**。不能通过换会话或修改草稿绕过。需要人工调查；未来恢复工具必须再次设计明确的权限和证据规则。

SQLite先记录发送意图，再发送网络请求。重启发现executing且已有发送意图时恢复为unknown；无发送意图则failed。重复确认、执行和跨会话相同已完成内容有本地去重防护。这不是跨设备的exactly-once保证，删除/回退数据库会损坏去重记录。

## 演示与验证

无需token的完整模拟演示：

```powershell
./.venv/Scripts/python.exe -X utf8 -m scripts.demo_v4
```

使用MockTransport，真实本地HTTP和SQLite，模拟评论/标签成功以及“服务端已接收但响应丢失”。每条场景重复执行后POST计数仍为1；最后只读核对恢复成功。结果在verification/v4-offline-demo.json。它不是真实GitHub写入成绩。

启动本地V4后，生成两个真实目标的**本地预览**：

```powershell
./.venv/Scripts/python.exe -X utf8 -m scripts.preview_v4
```

脚本会创建两个会话、读取已有标签、保存预览，绝不调用confirm或execute。结果在verification/v4-local-previews.json；再次执行会生成新操作和新标记，不要把旧确认用于新预览。

```powershell
./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/manual-v4-tests
```

程序全量161项通过，12条原有Chroma弃用警告；调整V4数据库默认位置后，迁移/API目标测试2项通过。真实Issue/标签读取与只读账号权限检查已通过。**真实写入验收状态以docs/v4-validation.md与实际verification文件为准**，模拟通过不能当成在线成功。

V2检索漏召回、模型追问偏多等问题未在V4优化。本版不引入V5前端、公开部署或性能指标；下一版等待用户指定。

### V4 权限修正后的验收补充

仅对明确的401/403/429拒绝，在修正原因后可以用原content_hash、完整确认文本及retry_after_attempt=N显式重确认。程序核对失败次数、当前草稿版本和目标，重新给出15分钟有效期；累计最多3次发送。旧确认不能重放到下一次失败，unknown仍不可重发。

本次写入回归37项通过（verification/v4-retry-test-results.xml）。真实评论与question标签第二次尝试成功，首次403记录保留；完整结果见docs/v4-validation.md。
