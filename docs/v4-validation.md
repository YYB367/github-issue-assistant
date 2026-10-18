# V4 开发与验证记录 — 2026-10-17

## 验证范围

全量 **161 passed**，0失败/错误/跳过，12条V2已有Chroma弃用警告，见verification/v4-test-results.xml。pip check通过。更改V4默认数据库文件名后追加迁移/API目标测试2项通过。未重新安装依赖，未新增第三方包，没有测负载、P95或跨平台表现。

新增34个参数化程序案例覆盖：评论/标签确认后执行；完整内容hash和确认文本；未确认拒绝；重复确认/执行；修改后失效；取消/重复取消；账号权限不足、PR、私有/归档/锁定仓库Issue、预检超时、不存在标签；4xx；发送后超时、5xx、非法响应、正文不符、重定向；只读核对成功及未找到；错误作者/目标/正文不能核对成功；保留既有标签；关闭写入、无token、改允许仓库；跨会话访问；Origin/Host；原子领取；执行中编辑；重启前后发送意图区分；过期；操作数量；分页上限与秒级时间；旧数据库迁移。

这些是确定性程序与故障模拟案例，属于开发/回归验证。未宣称它们是独立模型评估，也未覆盖V2原独立评估文件。

## 实际遇到的问题

1. 加Host限制后，旧手写ASGI断线fixture没有Host头而返回400。补上真实HTTP请求应有的Host头。
2. 普通BaseHTTP中间件干扰Request.is_disconnected，旧测试超时。改用纯ASGI同源检查，保留原receive/send，36项定向测试通过。
3. 过期测试错误地用previewed快照覆盖confirmed状态，得到confirmation_required。修正测试从数据库读取已确认对象后只修改expires_at。
4. 实现检查发现秒级GitHub时间与本机微秒since边界可能漏掉刚发布评论；扫描从创建前1分钟开始，明确仍不能消除所有时钟偏差，提供comment_id定点核对。
5. 初次启动V4失败，原数据库的单进程锁仍被用户从项目.venv启动的服务持有。没有删除锁；改用V4专用数据库并复制一致快照。
6. 一次验证脚本假定旧服务在8003，但该端口不监听，连接失败。V4的8004实际正常；最终记录仅包含已经核实的V4状态，不推断其他服务的端口。
7. 用户首次告知token已配置时，重新读取仍为空；确认保存后读取成功。仅检查是否非空，未输出token原文。

## 已执行的离线演示

verification/v4-offline-demo.json明确mode=offline_demo、github_network_calls=false。模拟真实HTTP路由、SQLite状态和GitHub传输：

| 场景 | 首次结果 | 重复执行后POST数 | 恢复 |
|---|---|---|---|
| 发布评论 | succeeded | 1 | 无需 |
| 添加已有标签 | succeeded | 1 | 无需 |
| 评论已收到但响应超时 | unknown | 1 | 只读核对后succeeded，仍1次POST |

上述离线演示没有访问GitHub；后续真实写入另见下文。

## 已执行的真实只读与本地验证

- GitHub Issue #1、已有标签接口HTTP200；该编号不是PR，已有question标签。证据：verification/v4-live-read.json。
- token保存后，/user身份YYB367、仓库账号写权限、目标Issue及question标签的只读预检均通过。**这不证明token的Issues写scope已经实际使用成功。**证据：verification/v4-live-preflight.json。
- SQLite备份完整性ok，复制8会话、7任务至sessions-v4.sqlite3；原会话/任务JSON逐一比较一致，新增operations表后schema_version=2。证据：v4-backup-check.json、v4-migration-check.json、v4-live-http-check.json。备份和数据库不在源码包中。
- 本地V4 /health、/docs可用。真实目标的评论与question标签已生成本地previewed记录，attempts=0，没有自动确认。证据：verification/v4-local-previews.json。

## 真实写入验收

用户明确授权完整测试评论（含操作标记）和question标签后，程序通过本地confirm/execute接口分别执行。**第一轮两项均被GitHub返回HTTP403**，status=failed、attempts=1，均未自动重试。评论失败后独立执行已经授权的标签测试，标签同样被拒绝。

首次错误记录只有状态码，未保留远端错误正文，不能断言403一定是哪个权限字段导致。已请用户核对token的仓库选择、Issues读写权限及审批状态。只读预检通过没有被当作写入成功。原始结果保存在verification/v4-live-write-attempt-1.json，后续若重验会另存记录，保留本次失败。

失败后再次GET Issue与评论：评论数0、标签为空、前100条未发现批准的操作标记。此时未产生预期写入。写入开关已在用户授权后启用；未来操作仍须独立确认，旧failed操作不能直接重发。

## 权限修正后的第二轮验收

用户告知已修正权限后，保留原授权的目标、完整评论、HTML标记与question标签，显式重确认第一次403失败的操作。两项均succeeded、attempts=2（第一次403，第二次成功）。重复调用execute仍为attempts=2，没有新增发送。

再次读取GitHub验证：评论ID6231125072、正文完全相同、作者ID317216629、目标Issue正确；前100条评论中匹配正文只有1条；标签包含question。[已发布评论](https://github.com/YYB367/learning-mcp-server/issues/1#issuecomment-6231125072)。证据为verification/v4-live-write-attempt-2.json；attempt-1原始失败记录未覆盖。

本次程序改动后，写入相关回归 **37 passed**，见verification/v4-retry-test-results.xml（原34项，加3项明确拒绝重确认测试）。此前全量161项的成绩对应此前代码；本次未重跑其余模块，不能表述为164项全量已通过。

仅对明确的401/403/429拒绝，在修正原因后可以用原content_hash、完整确认文本及retry_after_attempt=N显式重确认。程序核对失败次数、当前草稿版本和目标，重新给出15分钟有效期；累计最多3次发送。旧确认不能重放到下一次失败，unknown仍不可重发。

## 官方文档核对

- [GitHub创建Issue评论](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment)：固定POST评论接口及Issues写权限；只读核对使用同页评论读取接口。
- [GitHub添加Issue标签](https://docs.github.com/en/rest/issues/labels#add-labels-to-an-issue)：使用添加端点而不是替换/删除端点；执行前逐个读取现有标签。
- [GitHub仓库读取](https://docs.github.com/en/rest/repos/repos#get-a-repository)：核对公开仓库、归档状态和账号仓库权限。
- [Python SQLite backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)：复制一致快照；使用现有Python3.12内置模块。

## 已知限制与未验证风险

- 两类真实写入已在当前测试仓库验证；未验证其他仓库、不同账号角色或公开部署。
- 标签存在检查与写入之间有远端并发变化窗口；GitHub仍可能拒绝或返回与预期不同结果，程序会记录失败/未知。
- 评论核对有3页上限，标签核对只读前100个；匹配失败保留unknown。评论被修改/删除、时钟偏差及长期离线可能导致无法自动解除未知状态。
- 本地去重依赖数据库完整保留，不能承诺跨设备exactly-once。无unknown人工强制放行功能。
- V4数据库是V3快照，之后各自独立；旧实例的后续修改不会自动进入V4。脚本拒绝覆盖已有V4数据库。
- 仍限本机单用户、单进程。无账户认证、公开部署或GitHub App installation token支持保证；/user预检主要面向个人token。
- 未取消V2/V3已记录的检索与回答质量限制；所有公开草稿仍应人工审阅。
