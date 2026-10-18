# V3 开发与验证记录

日期：2026-10-16（Asia/Shanghai）。环境：Windows、Python3.12.6、SQLite3.45.3；沿用V2锁定依赖，无新增第三方包。

## 实际发生的问题与处理

1. 首次测试：6项通过、9项在fixture建立前发生Windows系统Temp目录拒绝访问，未把它们计为逻辑测试失败或通过。改用项目work下独立--basetemp目录后，目标15项全部通过。
2. 一条新测试使用空正则match产生pytest警告；删除无意义match参数，保留对异常code的断言。
3. 实现检查发现全局容量检查若放在去重之前，会让已提交任务的重试遇到429。将容量判断放到事务内幂等记录查询之后；测试验证两任务满载时仍返回原任务。
4. 实现检查发现旧API测试会使用默认实际数据库；改为每个API测试独立临时数据库，避免干扰演示数据。
5. 真实模型第二轮能利用新增信息，但追问偏多、重复确认版本、部分泛化建议引用弱。本轮没有继续调检索或提示词以掩盖质量问题。

## 程序测试（模拟模型/工具为主）

完整命令：pytest -q -p no:cacheprovider --basetemp=work/v3-test-tmp-2 --junitxml=verification/v3-test-results.xml。

结果：**127 passed，0失败/错误/跳过**，12条原有Chroma legacy embedding function config弃用警告。pip check：No broken requirements found。

新增12项覆盖：持久化重开、两会话隔离、补充与草稿进入上下文、旧版本编辑拒绝、并发写入、请求键复用/冲突、运行中取消与重复取消、失败保留草稿、迟到结果丢弃、重启遗留任务恢复、单进程锁、正常关闭清理、消息/补充/任务数量预算、24KB上下文预算、补充注入下程序目标校验、近期补充优先检索、容量控制、检索证据快照。部分测试包含多个相关断言。

此处验证业务行为，不计为检索召回或模型回答准确率。旧V1/V2程序测试全部保留。

## 真实 HTTP、GitHub、MCP 与 DeepSeek

证据：verification/v3-delivery-live-http.json（交付快照）、v3-live-http.json（演示输出）。

- 在8003启动0.3.0服务，创建真实测试Issue #1的会话。
- 两轮均completed；每轮2次MCP调用、3次模型请求，未触发输出修复。第一轮资料为D1第24–32行、D2第38行、D3第42–48行。
- 第二轮用户输入由演示脚本构造，明确标为**模拟**的npm.ps1执行策略报错、Node.js22/npm10，并非真实复现。GitHub读取、MCP进程、Embedding、Chroma、DeepSeek请求均为真实执行。
- 第二轮检索D1变为第38行npm.cmd说明，D2第24–32行，D3第42–48行。模型输出partial，注明模拟、文档版本与未验证限制；仍有7项追问和重复版本确认，简洁性不足。
- 同请求键重发返回同一task_id；旧revision草稿修改409；另一会话查询任务404；完成后人工备注保存，draft_source=user。
- 没有向GitHub发布评论、修改标签或其他写入。

## 真实进程重启

结束两轮后，核对本次启动的Python进程路径与PID，停止并重新启动V3服务，GET原会话。返回JSON与重启前final_session完全相等，保留2个任务、补充、检索证据、模型结果及人工草稿。证据：verification/v3-restart-check.json。

这验证了完成状态持久化；运行中崩溃恢复由遗留running任务单测覆盖，没有额外消耗模型调用做强杀中的在线实验。

## 官方资料核对

- [Python3.12 sqlite3事务控制](https://docs.python.org/3.12/library/sqlite3.html)：每次操作新连接，isolation_level=None配合显式BEGIN IMMEDIATE、commit/rollback；不跨协程共享数据库连接。
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)及[生命周期测试](https://fastapi.tiangolo.com/advanced/testing-events/)：启动恢复、退出清理，TestClient上下文运行生命周期。
- V3无新SDK/模型依赖；版本沿用requirements.lock，实际环境pip check通过。未重新执行跨平台或干净机器安装。

## 尚未验证与已知限制

- 没有账户权限、多用户部署、多进程、性能负载或P95验证。session_id不是安全令牌；只用于本机。
- 同步SQLite短事务在API事件循环内执行，超大数据库或磁盘异常可能阻塞；当前个人演示规模不引入任务队列/连接池。没有自动数据库备份、会话删除、数据迁移或跨会话检索。
- 每会话最多20次任务；不限总会话数，长期使用需自行管理磁盘。聊天只保留最近50条，历史任务完整保留到会话限额。
- 原生Embedding线程在取消后可能继续到结束；无实时工具轨迹流。任务重启后需要显式重试，不能恢复模型中间状态。
- 用户输入和模型输出会保存到本地数据库，用户应脱敏；配置密钥不被程序放入该状态。
- 旧V2独立检索失败仍保留。新增端到端两轮属于开发演示，不能当成独立回答质量成绩。V2独立评估文件未覆盖。
- V4操作确认、标签、发布和重复写入恢复尚未实现；本版待操作为空且状态disabled_in_v3。
