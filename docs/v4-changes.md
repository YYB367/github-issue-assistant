# V4 修改清单 — 2026-10-17

按用户要求，每次升级都列出实际文件、行为、验证和限制。

| 文件 | 本次改动 |
|---|---|
| app/github_write.py（新增） | 固定GitHub REST端点的两种写入工具；账号/公开仓库/Issue/标签检查；有界响应、错误分类、只读核对 |
| app/operation_store.py（新增） | 预览、内容hash、15分钟确认、原子领取、发送意图、结果、取消、去重和重启恢复 |
| app/operations.py（新增） | 标签查询、预览、确认、执行、查询、取消、核对接口；最多2个写入任务、60秒预算 |
| app/local_guard.py（新增） | ASGI同源修改检查，保留原有断线取消消息通道 |
| app/state.py | 新operations表和索引，schema_version=2；编辑/重新分析让预览和确认失效；会话返回待操作与状态 |
| app/api.py | 注册V4接口、操作恢复/退出处理、Host和Origin检查、版本0.4.0、写入配置就绪信息 |
| app/config.py、.env.example | 增加默认关闭的GITHUB_WRITES_ENABLED；默认数据库改为work/sessions-v4.sqlite3 |
| scripts/migrate_v3_state.py（新增） | 不覆盖目标的一致SQLite快照迁移 |
| scripts/demo_v4.py、preview_v4.py（新增） | 离线模拟写入与只生成真实目标本地预览的两个独立脚本 |
| tests/test_operations.py（新增） | 34个参数化程序案例，验证确认、权限、去重、未知结果、恢复、迁移等 |
| tests/test_api.py | 断线测试补上真实HTTP应有的Host头，保留取消语义断言 |
| README.md、docs/v4-*.md、verification/v4-* | 本次使用步骤、教学、修改和原始验证记录；旧README存档为docs/v3-readme.md |
| pyproject.toml | 项目版本0.4.0 |

重要运行变化：V3的原数据库仍有用户启动的服务持锁，V4采用独立数据库，已复制8个会话、7个任务。迁移是一次快照，之后两边不自动同步。原数据库另有本地备份，均不打包到源码ZIP。

设计取舍：模型继续使用原MCP只读工具。写入由明确的HTTP确认流程调用Python工具，不新增可被模型自行调用的MCP写工具，也不引入LangGraph或其他依赖。用户确认和程序校验仍是授权来源。

验证：全量161项通过；迁移/API目标测试2项通过；离线写入演示3场景成功；真实读取及只读权限检查通过。用户授权后第一轮真实评论、标签请求均被GitHub返回403，已保存失败记录并核对远端仍无评论/标签；用户修正权限后，按原内容显式重确认，第二轮两项真实写入均成功；首次失败记录继续保留。

## 本次补充修改

- `app/operations.py`：确认请求增加可选retry_after_attempt。
- `app/operation_store.py`：明确拒绝后可绑定失败次数重确认，保留原正文、标记及hash；累计发送次数，限制最多3次。仅对明确的401/403/429拒绝，在修正原因后可以用原content_hash、完整确认文本及retry_after_attempt=N显式重确认。程序核对失败次数、当前草稿版本和目标，重新给出15分钟有效期；累计最多3次发送。旧确认不能重放到下一次失败，unknown仍不可重发。
- `tests/test_operations.py`：新增3项防回归案例，写入相关37项通过。
- `verification/v4-live-write-attempt-2.json`：保存第二轮真实成功及只读核对结果，保留attempt-1的403证据。
