# V5 部署、备份与恢复

## 已验证的部署方式

当前工作区已在Windows、Python3.12.6、Chrome、CPU本地Embedding环境验证。使用FastAPI自带静态文件支持及Uvicorn单进程，绑定127.0.0.1。没有新增前端构建、Docker、消息队列或云服务。

新机器按README安装requirements.lock、创建.env、准备固定模型与知识库，然后执行：

```powershell
./.venv/Scripts/python.exe -m scripts.check
./.venv/Scripts/python.exe -m scripts.serve --port 8005
Invoke-RestMethod http://127.0.0.1:8005/health
Invoke-RestMethod http://127.0.0.1:8005/ready
```

请在项目根目录运行。启动检查失败时先看checks哪个字段为false。模型key未填或知识库未准备时仍可启动界面，但ready返回503，不能当作分析已可用。依赖/存储检查失败会阻止推荐启动入口；状态锁最终由API lifespan获取。

脚本固定单进程，不使用--reload或--workers。旧服务仍占用同一库时先在原终端Ctrl+C停止，再启动新版本；不要删除.owner.lock来绕过活进程。当前8005使用sessions-v5.sqlite3演示快照；它与旧实例的sessions-v4.sqlite3后续修改不互通，见README。

## 配置与持久化

| 内容 | 默认位置 | 迁移方式 |
|---|---|---|
| 凭证/模型/仓库设置 | .env | 在目标机器本地安全填写，不打进源码包 |
| 会话/任务/操作记录 | work/sessions-v4.sqlite3或STATE_DB_PATH | 停机后完整备份或SQLite backup；保留成功与unknown操作记录 |
| 知识库/快照/代际 | work/knowledge | 停止写入后完整目录复制，或按固定sources重建 |
| 本地模型 | work/models/bge-small-zh | prepare-model固定版本下载，或完整目录复制 |
| 生成token词表缓存 | work/token-cache | prepare-model准备；可重建 |
| 运维日志 | work/logs/events.jsonl | 轮转3个备份；按需归档，不替代业务状态 |

可覆盖的绝对路径：STATE_DB_PATH、KNOWLEDGE_PATH、EMBEDDING_MODEL_PATH、LOG_PATH。不要把状态库、.env或知识库目录挂在/static下。

## 备份与回滚

1. 停止原服务并确认没有执行中任务；有unknown的操作保留原记录，先做只读核对，不能用回滚抹掉未知状态后重发。
2. 对实际STATE_DB_PATH使用SQLite backup生成一个新文件；目标不存在时再创建，避免覆盖旧备份。V4迁移脚本只用于首次V3升级，不要反复覆盖状态库。
3. 保存代码包、锁文件及数据库备份的对应关系；知识库按完整目录保存，不单拷贝Chroma内部部分文件。
4. 更新代码、pip install锁文件、pip check、scripts.check，再启动唯一实例。检查ready并打开已有会话确认草稿、证据和操作状态仍在。

回滚代码时应先检查数据库兼容性。V5未改schema，仍为2，但新增JSON字段可能被旧严格响应模型拒绝；保留V5数据副本后测试旧版本，不能据此承诺任意版本回滚兼容。恢复旧数据库可能丢失之后已经成功的远端写入记录，从而破坏去重；有新写入后不能盲目回滚数据库。

## 个人服务器访问（说明，尚未跨平台实测）

如果服务器已有Python3.12，可按下面方式做私人访问。Linux安装和SSH隧道未在本次Windows环境实际验证；没有把它写成已部署的能力。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip check
# 在服务器本地配置.env，准备模型和知识库
.venv/bin/python -m scripts.check
.venv/bin/python -m scripts.serve --port 8005
```

在自己的电脑另开终端（将登录信息替换为实际个人服务器）：

```bash
ssh -N -L 8005:127.0.0.1:8005 user@your-server
```

然后浏览器打开http://127.0.0.1:8005。应用仍绑定服务器回环地址，SSH承担登录与连接加密。退出隧道不取消后台任务，回连后查询原任务和操作。

当前应用没有用户账户和逐会话访问授权；Host/Origin校验只防浏览器跨站触发，不能作为多用户身份认证。公开网络、多用户、反向代理域名、跨进程队列和容器发布未做验收，不提供“直接改0.0.0.0即可上线”的步骤。

## 排障

- health失败：看服务进程、端口和启动输出；端口冲突换一个本机端口，旧实例仍用独立数据库时不能共用锁。
- ready失败：查看返回checks；它不会验证DeepSeek网络和key有效性。
- 模型或GitHub失败：页面给出安全错误码和请求ID，在JSON日志按request_id/task_id查找。不要为排障打印.env或Authorization头。
- unknown：只读核对，评论可填已知comment_id；未找到保持unknown，不能通过换会话强制重发。
- 重启后：未完成分析恢复为failed；写入已有发送意图恢复为unknown，不会开机自动重发。

## 本版核对的官方资料

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)：启动/关闭共享资源的入口。
- [FastAPI StaticFiles](https://fastapi.tiangolo.com/tutorial/static-files/)：复用已安装Starlette提供静态页面。
- [FastAPI部署概念](https://fastapi.tiangolo.com/deployment/concepts/)：进程、重启、资源和部署前步骤；本项目选择单进程。
- [Python日志轮转](https://docs.python.org/3.12/library/logging.handlers.html#rotatingfilehandler)：使用标准库限制日志文件大小。
- Uvicorn settings网页本次访问超时；实际启动参数另用已安装0.54.0的帮助/运行结果核对，不把未读取页面当成依据。

## 当前工作区最终实例

最终代码运行于127.0.0.1:8008，STATE_DB_PATH指向work/sessions-v5-review.sqlite3，LOG_PATH指向work/logs/v5-review.jsonl。它从8005的已完成状态复制，旧进程未停止。切换代码时的进程终止命令被自动审批拒绝，故选择独立快照验收；不会自动同步两个实例。后续维护请只选择一个固定库和唯一实例，勿并行操作同一Issue的写入。
