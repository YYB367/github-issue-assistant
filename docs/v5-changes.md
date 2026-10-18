# V5 修改清单 — 2026-10-18

| 功能 | 入口与职责 | 相对V4的变化 |
|---|---|---|
| 工作台 | app/static/index.html、style.css、app.js | 新增单页操作界面，原HTTP接口继续可用 |
| 会话导航 | app/state.py StateStore.listing；app/sessions.py GET /sessions | 最多50条/页，列表不带草稿与聊天；按允许仓库筛选 |
| 静态页面与错误响应 | app/api.py create_app | /、/static、/ready；V5版本号；输入校验不回显原值；意外错误仅返回安全错误码 |
| 分阶段指标 | app/engine.py phase / ask_model / run；app/schemas.py AnalyzeResponse | timings_ms、usage_reported_calls；结果继续随任务保存 |
| 写入指标 | app/operations.py execute_operation；app/operation_store.py complete | 预检/发送/总耗时写入原操作JSON；确认与去重规则保持V4行为 |
| 安全事件日志 | app/telemetry.py EventLog / RequestTelemetryMiddleware | 标准库轮转日志，请求ID、路由模板和允许字段；中间件拦截原始异常；生命周期关闭handler |
| 配置就绪 | app/readiness.py readiness；scripts/check.py inspect | /ready仅本地快速检查，CLI检查锁定依赖、目录写权限、SQLite quick_check |
| 启动入口 | scripts/serve.py main | 绑定127.0.0.1、单进程、关闭原始URL访问日志，配置错误不打印原始异常 |
| 离线演示 | scripts/demo_v5.py demo_app | 隔离状态、假模型/工具/GitHub，固定模拟证据，不加载.env |
| 验证脚本 | tests/test_v5.py、scripts/browser_smoke.py、scripts/live_check_v5.py | 程序边界、离线Chrome交互、真实只读模型/MCP验收分别记录 |

没有新增应用运行依赖。requirements-browser.txt仅供可选浏览器验收。pyproject版本改为0.5.0；.env.example增加可选日志路径说明。没有引入LangGraph、前端框架或新数据服务。

V4数据库schema仍为2，旧JSON任务缺少新指标时界面显示未提供。当前8005使用原库快照以避开旧实例持锁，快照非自动迁移策略，生产继续使用一个固定数据库路径。备份和当前快照均不进入交付包。

最终验收进程使用8008和sessions-v5-review.sqlite3，复制12会话、8任务、6操作；8005初次实现进程未强停。原因是进程终止命令被自动审批拒绝。对应快照与HTTP检查在verification/v5-final-review-state.json、v5-live-http.json；不是自动多实例同步功能。
