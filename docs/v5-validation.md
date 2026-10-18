# V5 开发与验证记录 — 2026-10-18

## 实际结果

| 验证层 | 本次实际结果 | 原始记录 |
|---|---|---|
| 程序回归 | 172 passed；12条既有Chroma弃用警告，0失败 | verification/v5-test-results.xml |
| V5边界目标测试 | 8 passed | verification/v5-targeted-tests.xml |
| Chrome离线界面 | 8组流程通过，0页面脚本错误；模拟模型/工具/GitHub | verification/v5-browser-check.json |
| 真实只读分析 | completed；真实MCP工具2次、模型3次、向量文档片段3条；证据partial | verification/v5-live-read-only.json |
| 最终服务 | 8008的根页面、静态文件、docs、OpenAPI均HTTP200；health ok、ready ready | verification/v5-live-http.json |
| 持久化 | 关闭并重开应用lifespan后，已有真实分析会话JSON完全相同；没有宣称OS进程重启成功 | verification/v5-restart-check.json |
| 凭证排除 | 对配置中的实际key/token执行日志字节匹配，无命中；源码包另行检查 | verification/v5-log-scan.json |
| 运行兼容 | Python3.12.6；FastAPI0.143.0、Pydantic2.14.1、MCP1.30.0、OpenAI3.19.2、Chroma1.5.9、FastEmbed0.9.0；pip check通过 | verification/v5-startup-check.json、v5-dependency-check.txt |

最终全量是在日志异常处理和SQLite连接关闭修正后运行；没有把此前171项的成绩当作最终172项。新增V5程序案例8项，原V4及以前164项一并执行。

本次没有调用真实GitHub写入确认/执行。真实写入成绩仍仅指V4中用户明确授权的测试。V5浏览器使用FakeGitHub验证操作：正常演示评论与标签各1次POST，共2次；超时演示1次POST后unknown，GET核对恢复succeeded，仍只有1次POST。模拟成绩不替代V5真实写入现场验收。

## 离线界面覆盖

1. 提交链接、查看两条实际工具循环轨迹及模拟文档；script标签作为文本显示，未执行。
2. 未勾选/错误确认文本无法执行；修改草稿后旧预览失效，没有发送。
3. 完整确认后模拟评论成功；重复execute后POST数仍1。
4. 刷新恢复会话且不重发；读取已有标签、预览和确认添加。
5. 保存补充、创建第二次分析任务。
6. 新会话没有旧补充/草稿；取消进行中的分析。
7. 取消预览不发送；390px手机视口无页面横向溢出。
8. 模拟GitHub收到写入但响应丢失：unknown不提供重发入口，只读核对成功。

截图：verification/v5-ui-desktop.png、v5-ui-mobile.png是离线演示；v5-ui-live.png是真实只读分析界面。

## 真实只读结果的含义

对测试Issue #1的一次调用实际耗时21473.07ms，接口返回prompt_tokens=6123、completion_tokens=2411、total_tokens=8534，3次模型调用均提供usage。结果包含D1/D2/D3三条向量文档片段，模型判为partial并继续追问环境与错误信息。

这只是一次现场结果，不是P95、吞吐量、成本基准或模型准确率。未复现npm安装失败，没有验证建议执行效果，也未更改V2检索阈值、混合召回或模型提示词。V2/V3原有质量限制继续有效。

## 实际遇到与修正的问题

- 初次静态文件写在了工作区外层app/static，导致项目静态目录不存在。已移动到交付项目app/static，实际HTTP和浏览器均核对路径正确。
- 启动检查将requirements.lock里的 `; sys_platform == ...` 当作版本字符串，误报依赖不兼容。使用PEP508解析并评估条件标记；新增回归案例，实际依赖无冲突。
- Playwright的wait_for_function内部动态求值被CSP拒绝。测试改用DevTools page.evaluate轮询，没有给产品页面添加unsafe-eval或关闭CSP。
- SQLite只读检查的with连接仅管理事务、不自动关闭，Windows清理临时库时发现句柄占用。改用contextlib.closing；随后临时库清理和删除后ready失败的测试通过。
- 手机布局中64位hash未断行导致页面宽度溢出。给段落加overflow-wrap:anywhere后390px浏览器断言通过。
- 旧实例持有原库锁，新启动拒绝。保留原实例，先建立V5一致快照；最后进程终止重启命令又被自动审批拒绝，因此用第二份独立快照在8008运行最终代码。未删除锁、未终止旧实例、未宣称两个状态库自动同步。
- 代码检查发现仅注册Exception handler仍可能让ASGI服务器重记原始异常。改在用户中间件中捕获并返回安全500，只记异常类型和错误码，避免原始上游消息进入服务日志。

## 当前状态与限制

- 当前最终验收入口为http://127.0.0.1:8008，使用work/sessions-v5-review.sqlite3（复制时12会话、8任务、6操作），日志为work/logs/v5-review.jsonl。8005早期实例、8006模拟实例及用户原实例均未强制终止；请只把8008作为本次继续处理的入口，后续维护采用一个固定库、一个实例。
- 应用lifespan关闭重开持久化已验证；OS进程终止重启受审批限制未完成。明确记录该区别。
- 尚无多用户认证、逐会话授权、公开部署、跨进程队列与跨数据库去重；Host/Origin检查不能替代这些能力。
- ready只检查配置与文件标记，不保证远端可用、模型权重完整或检索质量。prepare-model和实际任务会做进一步校验。
- 模型用量只覆盖收到usage的响应，失败请求的远端账单可能不完整；没有成本优化承诺。
- 检索线程超时后底层线程可能继续结束当前计算；不能声称支持任意底层算子强杀。
- 未测长期负载、P95、资源上限、Linux/systemd/容器、移动设备实机或其他浏览器。

## 案例集与后续建议

本版新增案例属于开发/回归集；V1–V4的开发与最终评估文件继续保留。没有用这些开发流程冒充独立评估，也没有把工具、证据、回答和操作合并成一个“准确率”。

建议下一步先由用户在离线界面练习并人工复核一次真实只读结果，再选择一个固定状态库。若继续迭代，优先补独立问题样本和证据支持度评估，分析检索失败原因后再决定是否改检索。公开部署或多用户支持须作为新的明确范围；本版不自动进入下一版本。
