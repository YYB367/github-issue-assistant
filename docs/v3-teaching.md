# V3：用当前代码理解状态与多轮

## 1. 为什么需要独立业务状态

V2 的 AnalysisRunner.messages 只活在一次请求里。V3 新增 StateStore；sessions 保存当前目标、补充、草稿、成功分析及 active_task_id，tasks 保存每轮的输入快照、完整输出和执行状态，messages 只保存展示用的最近50条用户输入/草稿与助手回复。三个概念分别存，不会把聊天文本当成任务状态。

看 app/state.py 的 create/get/start/finish：session_id 稳定，task_id 每次新分析不同；finish 在同一事务中写任务结果和会话草稿，成功结果里的 retrieval 保留片段、提交、hash、行号、距离和引用。失败不覆盖上一轮成功结果。

当前 SQLite 中采用 JSON 保存嵌套业务快照，SQL 列只索引会话/任务/请求键。这样不必为每个模型字段拆表，代价是复杂跨会话分析不方便；个人项目目前无需 ORM。凭证来自 Settings，不写入业务状态；用户自己输入的文本会原样持久化，所以输入应先脱敏。

验证：test_round_trip_isolation_and_context 用两个会话证明补充不串会话、任务跨会话查询404，并重新打开应用读回完全相同状态；test_session_snapshot_keeps_retrieval_and_task_history 验证引用片段确实保存。真实HTTP重启记录也比对了整个会话。

## 2. 为什么旧页面不能直接写草稿

假设页面读到 revision=3，另一次编辑把它变成4。旧页面再提交 expected_revision=3 时，StateStore._editable 拒绝并返回409/revision_conflict。检查、写入、版本递增放在 BEGIN IMMEDIATE 短事务内；模型与网络请求在事务外，避免长时间占用数据库锁。

start 写入 request_key 与该次 expected_revision 的签名；请求参数目前只有这两个字段，同一个键和相同版本重发返回原 task_id。更换版本却复用同一键返回409/idempotency_conflict。开始分析、结束分析都会递增会话版本。运行中禁止补充或改稿，减少“旧任务覆盖新编辑”的分支。

验证：两个线程以同一版本编辑，只有一个成功；重复提交不会新增任务；取消后迟到的 completed 不能覆盖取消状态。幂等键是本地分析任务去重，不是将来GitHub评论的去重实现。

## 3. 多轮到底把什么交给模型

StateStore.start 构造 continuation：全部允许范围内的 supplements、previous_summary 的前1000字符、current_draft。它不读取 messages，也不带上一轮的工具轨迹和检索片段。最多12条补充、合计6000字符、草稿3000字符，再用UTF-8 24000字节硬限制；超限报错，不悄悄截断补充。摘要截取可能丢失细节，但原任务完整结果仍保留。

AnalysisRunner.run 将该快照标为数据，系统规则明确旧摘要和草稿不是证据、不能授权新工具或改变目标。随后仍由模型调用 get_issue/list_issue_comments。retrieve_evidence 把最新补充放在查询开头，防止较长旧Issue占满Embedding输入预算；V2仍会按实际tokenizer限制查询。

真实第二轮：模拟补充npm.ps1执行策略错误后，D1变成README第38行npm.cmd说明；第一轮D1原是第24至32行安装步骤。引用编号每轮独立，旧D1不能当成新D1使用，旧证据留在原task中。

验证：测试检查第二轮模型消息含补充和草稿、不含旧tool_trace；单测保证最新补充在检索查询前部；即使补充要求访问evil/repo，工具参数校验仍拒绝。模型语义上的所有提示注入效果没有被完全证明，已验证的是程序目标/工具边界。

## 4. 后台任务、取消与恢复

app/sessions.py 的 start 先把running任务落库，再创建asyncio任务，HTTP立即返回202。最多同时两个V3任务；任务自身继承90秒总预算。用户通过GET查询最终结果；取消先持久化cancelled再取消协程，因此迟到输出不能改写取消状态。

app/api.py 的 lifespan 持有数据库对应的FileLock，明确单进程所有权；否则第二个进程可能误把第一个进程的running任务当成崩溃任务。启动时 recover 将遗留running置为failed/server_interrupted；正常关闭会取消并等待当前协程清理。恢复的是业务状态，不是DeepSeek请求或MCP内部执行位置。

验证：测试第二个实例被锁拒绝、关闭后释放锁、运行中取消、双重取消、退出清理、模拟遗留任务恢复。实际重启验证是在两轮已经完成之后进行，证明结果保存；真实杀进程时恰好处于模型请求中没有另行试验。

## 5. 草稿与未来操作状态

PATCH draft 只修改当前draft、设置draft_source=user，保留latest_result原始分析，便于比较。下一轮成功分析会再生成草稿；需要完全保留人工最终文本时，在最后一轮后编辑。

pending_operations 和 operation_status 已保存，但V3固定为空和disabled_in_v3；没有伪造“待确认评论”或提前实现V4。session_id和UUID格式校验只解决定位与归属，不是登录权限；当前服务面向127.0.0.1单用户。

仍有问题：真实模型第二轮追问7项，重复确认Node版本，并未完全按“尽量简短”要求缩短；引用存在也不代表语义支持充分。程序将这些输出如实保留，文档不把“多轮接通”写成“回答质量已解决”。
