# GitHub Issue 分析与处理助手

基于 Python、FastAPI、官方 MCP SDK、DeepSeek、Chroma 和 SQLite 的本机单用户项目。提交 GitHub Issue 链接，查看实际工具调用、结构化分析、检索依据和回复草稿；在自己的测试仓库中，经过具体内容确认后添加已有标签或发布评论。

当前版本 **0.5.1**：已完成 V1～V5 的主流程，并补充双击启动、自动备份及只读演示案例。面向安装、依赖和配置问题；不自动修改代码或关闭 Issue。

## 功能与代码

| 功能 | 主要代码 |
|---|---|
| 模型决定读取工具、程序校验和执行 MCP 调用循环 | `app/engine.py`、`app/mcp_client.py`、`mcp_server/` |
| 固定版本 Markdown 入库、向量检索与来源返回 | `knowledge/`、`knowledge/sources.json`、`scripts/kb.py` |
| 多轮补充、草稿修改、会话隔离与任务取消 | `app/sessions.py`、`app/state.py` |
| 操作预览、内容绑定确认、防重复提交与未知结果核对 | `app/operations.py`、`app/operation_store.py`、`app/github_write.py` |
| 简单网页、健康检查、安全日志与模型用量 | `app/static/`、`app/api.py`、`app/telemetry.py` |
| 双击启停、固定数据库、自动备份与停机恢复 | `scripts/launcher.py`、`app/backups.py`、`scripts/storage.py` |

MCP 服务使用 Python 官方 SDK，通过 stdio 由应用启动，不需要另装 Node.js。普通分析只访问配置允许的一个公开仓库；FastAPI 演示案例有单独的固定目标和只读限制。没有引入 LangGraph、多 Agent 或额外队列。

## 首次安装

已在 Windows、Python 3.12.6 和本机 Chrome 验证。使用 **Python 3.12**，应用依赖锁定在 `requirements.lock`；浏览器测试依赖单独列在 `requirements-browser.txt`。首次安装需要下载依赖。

```powershell
git clone https://github.com/YYB367/github-issue-assistant.git
cd github-issue-assistant
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock
./.venv/Scripts/python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

私有仓库的克隆需要对应账号权限。已有 `.env` 不要覆盖；密钥只填写在本机文件中，不发送到聊天或提交 Git。

- 只体验离线教学：将 `.env` 中 `KNOWLEDGE_ENABLED=false`，无需填写任何密钥。
- 真实公开案例：额外配置 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL`，保持 `KNOWLEDGE_ENABLED=false` 即可先体验。
- 自己的仓库：修改 `ALLOWED_REPOSITORY`；需要知识库时，先将 `knowledge/sources.json` 配置为该仓库的具体提交与文档路径，再按下文准备和入库。
- 真实写入：仅在自己的测试仓库启用 `GITHUB_WRITES_ENABLED=true`，配置限定仓库、Issues 读写权限的 `GITHUB_TOKEN`，每次仍需确认完整操作内容。

```powershell
# 本地配置和依赖检查，不会请求模型或 GitHub
./.venv/Scripts/python.exe -m scripts.check
```

未配置模型或未准备启用的知识库时，检查会如实返回 `not_ready`。离线教学仍可从工作台使用，不应把它当作真实分析已就绪。

## 现在怎么用

在项目目录双击 **Start Issue Assistant.bat**。启动器使用本项目.venv，等服务健康后打开默认浏览器。重复双击会核对项目、版本、数据库和运行实例，再打开原页面，不会换一个库另起服务。

结束时双击 **Stop Issue Assistant.bat**，或在启动窗口按Ctrl+C。停止入口只控制启动器登记的本实例；有GitHub写请求正在执行时拒绝停止，等结果完成后再试。正常停止会等待最后一次备份。关闭浏览器页面不会停止服务。

默认入口是 [http://127.0.0.1:8008](http://127.0.0.1:8008/)，端口由 `.env` 的 `LAUNCH_PORT` 指定。也可在项目目录执行 `./.venv/Scripts/python.exe -m scripts.launcher`。

## 一份固定数据库

新安装默认使用项目内的 `work/sessions-v4.sqlite3`（文件名沿用历史版本）。也可在 `.env` 设置 `STATE_DB_PATH`。已有用户应继续沿用实际在用的数据库路径，升级时保留 `.env` 与 `work/`，不要为了换端口新建库。仓库不携带开发机器上的会话、凭证、备份或模型文件。

- 分析结果、补充信息、人工保存的草稿和操作状态都提交到SQLite。
- 未点击保存的草稿仍属于未保存编辑，页面会提示；备份不包含这些编辑。
- 后台串行备份，连续保存短时间合并；自动保留最近10份。备份失败单独显示，不影响已提交的数据。
- 自动备份使用SQLite官方backup API，不复制正在运行的数据库主文件。
- 修改旧数据库结构前先做保护备份；恢复前也保护当前库。保护备份不参与自动10份清理。
- 相对配置路径以项目目录为基准，不因从哪个目录启动或换端口而变化。

备份默认位于主库旁的 `backups/`。每份备份是一对同名 `.sqlite3` 和 `.json` 文件（内容校验与来源信息）。重要演示后，请把**这两个文件一起**复制到云盘或外置存储。同一磁盘的备份不能防磁盘损坏。

启动器不会从多个旧库中自动切换或合并。需要迁移数据时，先核对实际数据路径和操作历史，再使用下文的备份与恢复命令。

## 不需要很多自己的GitHub项目

工作台“没有自己的Issue？选择一个只读案例”提供两种入口：

| 入口 | 实际行为 | 所需凭证 |
|---|---|---|
| FastAPI真实公开案例（3个） | 实时读取真实Issue/评论，经官方MCP客户端和DeepSeek分析，结果保存到同一主库 | DeepSeek key；不使用GitHub token |
| 离线教学案例（6个） | 本地预编写的固定结果，练习查看、补充、改稿和保存 | 无需网络和密钥 |
| 原测试仓库 | 沿用完整分析、项目知识库及人工确认写入 | 公开读取可不带GitHub token；写入才要求token |

公开Issue的读取接口支持匿名访问，GitHub对匿名请求的限额通常为每IP每小时60次，实际以响应为准。[GitHub限流说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

FastAPI案例仅允许程序预设的目标，始终只读，不向MCP传入你的写入token，也不使用你自己仓库的知识库。未导入FastAPI文档时不能声称已核对其文档。案例是历史问题，关闭状态或历史回复不等于已验证方案。

教学案例明确标注“固定教学结果”，模型/MCP/GitHub调用数均为0，不伪造真实工具轨迹。补充可以保存，但不会让固定结果重新推理。

真实公开案例：

- [#2582：Uvicorn无法导入app模块](https://github.com/fastapi/fastapi/issues/2582)
- [#1093：multipart/form-data解析问题](https://github.com/fastapi/fastapi/issues/1093)
- [#2365：表单中提交文件与对象](https://github.com/fastapi/fastapi/issues/2365)

## 准备项目知识库（可选）

默认来源是 `YYB367/learning-mcp-server` 的固定提交 README，不能用于证明其他项目的解决方案。核对 `knowledge/sources.json` 与允许的仓库一致，再执行：

```powershell
./.venv/Scripts/python.exe -m scripts.kb prepare-model
./.venv/Scripts/python.exe -m scripts.kb sync-docs
```

自己测试仓库的写入仍要求GITHUB_WRITES_ENABLED=true、正确GitHub权限和每次具体确认。公开案例与教学案例在程序层禁止写入，不能通过改按钮或直接HTTP请求绕过。

## 备份与恢复

在项目目录打开终端：

```powershell
# 列出当前主库的备份
./.venv/Scripts/python.exe -m scripts.storage list
# 额外生成一次备份（运行中也可以）
./.venv/Scripts/python.exe -m scripts.storage backup
```

恢复会替换当前库。先双击Stop Issue Assistant.bat，确认服务停止，再选择list列出的实际文件名：

```powershell
./.venv/Scripts/python.exe -m scripts.storage restore auto-实际文件名.sqlite3 --confirm-restore
```

恢复命令核对来源、内容哈希、SQLite完整性和占用锁，拒绝损坏备份、其他数据文件的备份，以及会抹掉较新GitHub发送记录的回退。当前库误删后仍可恢复；检测到主库缺失但有备份时，推荐启动器拒绝悄悄新建空库。

恢复后真实GitHub写入暂停，读取与分析可以继续。核对GitHub远端与操作记录，确认不存在漏记或未知发送后，人工执行：

```powershell
./.venv/Scripts/python.exe -m scripts.storage acknowledge-restore --reviewed-github-history
```

若磁盘更换或搬到新目录：把备份SQLite和同名JSON复制到新配置的backups目录，确保目标数据库不存在，恢复命令额外加 `--allow-new-location`。该选项只用于明确的异地恢复，不允许覆盖已存在的其他库；恢复后仍暂停写入。

这不代替每条操作的内容确认。无法核对时保持暂停。恢复不是撤销已经发布到GitHub的评论。恢复工具已在隔离测试库验证，本次没有回退你的真实主库。

## 代码、教学与验证

[本次修改与原理](docs/convenience-changes.md) · [实际验证记录](docs/convenience-validation.md) · [V5原版说明](docs/v5-readme.md)

常用入口：/health表示存活，/ready表示本地配置就绪，/storage/status分别报告保存与备份状态，/docs保留API文档。JSON运维日志不包含密钥、原始请求内容或本地控制令牌。

```powershell
./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/my-tests
```

当前程序回归与验证边界见 [验证摘要](docs/validation-summary.md)。原始运行记录、截图和个人练习对话保留在开发机器，不随 Git 提交；历史文档中的 verification 路径是当时的本地证据，并非克隆后自带文件。各版本 README 是开发存档，新安装以本 README 为准。

不把教学案例当作独立评估，不宣称未经测量的准确率、P95或吞吐量。本版仍限本机单用户和唯一活跃主库，没有用户身份认证，不适合直接暴露到公网。不能承诺数据库误删后恢复到最后一个未备份瞬间，也不能用同盘备份承诺磁盘损坏后的找回。

## 项目来源

本项目参考 [learning-mcp-server](https://github.com/YYB367/learning-mcp-server) 的 GitHub 读取与 MCP 实践，以及 [langchain-study-assistant](https://github.com/YYB367/langchain-study-assistant) 的文档检索与来源返回实践，在独立目录实现。实际复用与限制见 [参考代码审查](docs/reference-review.md)，两个原始仓库未作修改。
