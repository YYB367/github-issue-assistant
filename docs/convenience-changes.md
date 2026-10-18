# 便捷体验优化：修改与原理

## 选择与边界

本机Demo的主流程已完成，此次没有引入新运行依赖。选择沿用最完整的旧主库，不迁移目录、不按端口分库、不做数据集管理。把启动登记、备份文件和业务数据库分别用于进程发现、数据保护和业务状态，不混作聊天记忆。

## 双击启动 / 停止

- `Start Issue Assistant.bat`：切到脚本所在项目目录，调用本项目.venv与 `scripts.launcher`。首次安装缺失环境时给出提示，失败保留窗口。
- `scripts/launcher.py`：用FileLock串行处理重复启动。通过 `/instance` 的项目、版本、数据库路径指纹及run_id验证实例，不能只凭端口或PID。`wait_and_open`只有健康检查成功后才请求默认浏览器打开。
- `app/instance.py`：只返回运行身份，不返回凭证或停止控制令牌。数据库身份与端口无关，换端口仍指向.env同一个文件。
- `Stop Issue Assistant.bat` / `--stop`：使用本机登记中的私有控制令牌请求 `/__local/stop`，只停止匹配项目和数据库的托管服务。令牌不返回到前端、不传给模型、不记入日志。服务有写入任务时拒绝停止；其他任务由原lifespan关闭逻辑清理并备份。

正常关闭使用停止脚本或Ctrl+C。直接结束进程、关闭控制台或断电可能来不及完成最后一次备份，但此前SQLite已提交的数据与最近成功备份仍是独立保护层。

## 自动保存与自动备份

`StateStore.transaction`在commit成功且有实际数据变化后通知BackupManager；只读查询不触发备份。通知不执行磁盘备份，不让备份失败把已提交事务误报成保存失败。操作记录的变化也触发备份，保护去重和未知状态。

`app/backups.py` 的 `BackupManager`用一个后台任务合并短时间保存，在工作线程串行调用SQLite Connection.backup。源数据库即使使用WAL、其他连接仍存在，备份也包含已提交快照。快照先写临时文件，校验后发布正式文件与同名JSON信息。后台备份有时间预算；失败只记录安全错误码。

保留最近10份auto备份，manual和protected另保留。每份记录有数据库路径身份、schema版本、创建时间与SHA256；只清理属于当前数据文件的自动备份。升级旧schema前先保护；当前更新未改变schema2，但已经额外生成更新前保护备份。

页面的业务保存状态依据已提交会话与未保存编辑，备份状态独立由 `/storage/status` 返回。备份失败时明确显示失败和最近一次成功时间，不把两件事混为一谈。

## 恢复为什么比复制文件多几步

`scripts/storage.py restore`只操作当前.env配置的数据库，先获得同一个.owner.lock，拒绝在线恢复。验证来源、哈希和SQLite完整性；对当前库做保护备份，处理WAL后再原子替换。复制的是已经完成的备份文件，不是在线主库。

恢复旧数据可能抹掉防重复写入记录，所以会比较已发送操作，拒绝丢失较新的发送历史；恢复后还建立restore-hold标记，程序禁止真实GitHub写入，直到操作者核对远端历史。`acknowledge-restore`只解除这个暂停，不代替V4的逐操作确认。主库误删时无法从本机判断备份之后的远端发送，仍必须人工核对。

异地或更换磁盘时，只有显式传入--allow-new-location且目标文件不存在，才允许恢复不同原路径的备份；不据此覆盖现有其他库，恢复后仍暂停写入。

备份恢复只覆盖SQLite业务状态；不回滚GitHub远端、.env、Embedding模型或Chroma知识库。知识库可按固定版本重建，密钥仍由环境配置。

## 案例如何增加而不放开写权限

`cases/catalog.json`保存3个FastAPI公开历史目标与6个本地教学案例。`app/examples.py resolve / runner_for`从固定ID解析目标，校验链接完全一致。

真实公开案例每个任务创建限定仓库的Settings副本：GitHub token清空、写入关闭、知识库关闭。`connect_tools`仍启动官方MCP stdio子进程，向子进程明确注入空token。模型决定两个只读工具的实际调用，参数和预算校验沿用V1。

不把自己仓库的README拿去支持FastAPI答案。没有导入FastAPI文档时documentation_checked=false，检索为空。历史评论属于外部数据，关闭Issue不证明方案正确。

教学案例由 `TeachingRunner`返回本地预编写Analysis，mode=teaching_case、model_calls=0、tool_trace为空，页面明确标注。它用于练习界面与数据保存，不是模型效果评测。

会话和任务保存example_id/source，但仍共用唯一主库。`app/operations.py target`及 `OperationStore.preview`都拒绝示例会话；只读边界由程序强制，不能靠UI或模型自觉。

## 文件职责

| 文件 | 新增/修改 |
|---|---|
| app/config.py | 备份开关、启动端口；相对路径以项目目录解析 |
| app/backups.py | 快照、校验、保留策略、升级保护和后台合并任务 |
| app/state.py / api.py | 提交后通知、生命周期备份、状态接口、受保护停止入口 |
| app/examples.py / cases/catalog.json | 固定公开案例与诚实标注的教学案例 |
| app/sessions.py / schemas.py | 案例会话/任务、模式字段；普通流程仍兼容 |
| app/operations.py / operation_store.py | 示例只读、恢复后写入暂停 |
| app/static/convenience.js | 备份状态和案例选择；复用原页面操作 |
| scripts/launcher.py / storage.py | 双击服务管理与命令行恢复 |
| tests/test_convenience.py | 快照、恢复、身份、失败、只读案例等回归验证 |

原V5源码包和原始浏览器证据保留；本次记录使用convenience前缀，版本号0.5.1。
