# GitHub Issue 分析与处理助手 — V5

面向小型公开仓库维护者的本机工作台：提交Issue链接，读取正文/评论，检索固定提交的资料，查看有来源的初步建议，补充信息、编辑回复，再逐项确认发布评论或添加已有标签。

当前只允许 `YYB367/learning-mcp-server`，重点处理安装、依赖、配置问题。模型只获得两个只读MCP工具；GitHub写入由程序检查并执行。项目不修改代码、不关闭Issue。

本工作区最终验收入口：[打开 V5 工作台](http://127.0.0.1:8008/)。该实例使用 `work/sessions-v5-review.sqlite3`，从8005实例的已完成状态复制，保留真实分析会话。旧进程终止命令被自动审批拒绝，因此采用独立快照与端口，未停止旧服务；快照之间后续不自动同步。下面8005是标准安装示例端口。

## 本版修改

- 新增HTML/CSS/原生JavaScript工作台：会话恢复、任务取消、证据、调用记录、草稿编辑、完整操作预览、明确确认与未知结果核对。
- 新增本地启动检查、`/ready`配置就绪检查、轮转JSON日志和分阶段耗时。token用量来自模型接口，不估算成本。
- 沿用V4的SQLite业务状态与内容绑定确认，默认数据库路径不变，没有新增数据库迁移。
- 提供隔离离线演示、真实浏览器验证脚本与本机部署步骤；没有新增应用运行依赖。

详细文件职责：[修改清单](docs/v5-changes.md) · [代码教学](docs/v5-teaching.md) · [验证记录](docs/v5-validation.md) · [部署与恢复](docs/v5-deployment.md)。V4说明归档在docs/v4-readme.md，历史验证文件保留。

## 安装与配置

在本项目目录使用Python3.12。锁定版本见requirements.lock；本版沿用原验证版本，具体兼容性见启动报告。

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.lock
./.venv/Scripts/python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本机.env填写DEEPSEEK_API_KEY；DEEPSEEK_BASE_URL、DEEPSEEK_MODEL也由环境配置。不要把密钥粘贴到Issue、补充信息或聊天。新机器准备固定版本知识库：

```powershell
./.venv/Scripts/python.exe -m scripts.kb prepare-model
./.venv/Scripts/python.exe -m scripts.kb sync-docs
./.venv/Scripts/python.exe -m scripts.check
```

初始资料只有固定提交README，独立安装说明与FAQ在参考仓库中不存在；程序不能声称读过。同步历史Issue是可选的受限管理命令，见V2说明。仅想先试读取时，可配置KNOWLEDGE_ENABLED=false；不会返回文档建议。

GITHUB_TOKEN只用于固定GitHub接口。开启写入需将GITHUB_WRITES_ENABLED=true，配置仅允许自己测试仓库的Issues读写token并重启。每条操作仍需审阅与明确确认，token不代替授权。

## 启动与演示

先停止使用同一状态库的旧实例，再启动单进程服务：

```powershell
./.venv/Scripts/python.exe -m scripts.serve --port 8005
```

打开 [工作台](http://127.0.0.1:8005/)，API文档在[/docs](http://127.0.0.1:8005/docs)。默认仍使用work/sessions-v4.sqlite3，可通过STATE_DB_PATH指定绝对路径。旧进程占锁时启动会拒绝，不删除锁文件绕过。

本次工作区因已有实例占用原库，当前8005演示使用 `work/sessions-v5.sqlite3` 一致快照（11会话、7任务、6操作）。原实例未停止；两个库之后独立，不能自动合并。继续本次演示时在启动命令前设置：

```powershell
$env:STATE_DB_PATH=(Join-Path (Get-Location) 'work/sessions-v5.sqlite3')
./.venv/Scripts/python.exe -m scripts.serve --port 8005
```

新安装无需使用这个演示快照，也无需逐版本新建数据库。状态库、模型、.env和日志都不包含在源码包中。

1. 提交 https://github.com/YYB367/learning-mcp-server/issues/1 ，等待分析完成。
2. 查看摘要、信息缺口、引用片段、版本/行号，以及实际MCP调用和用量。
3. 保存补充信息，点击继续分析；编辑草稿后先保存。刷新页面可恢复本标签页会话，也可从最近会话或ID打开。
4. 点击评论或已有标签的预览，检查目标和完整正文（包含HTML操作标记）。勾选已核对，再输入显示的完整确认文本，点击确认并执行。
5. 改稿后旧确认失效。取消预览不会发请求；写入已执行时不能撤回。unknown只允许只读核对；未找到不代表可以重发。

界面使用普通文本展示Issue相关内容和证据，不执行其中HTML、脚本或指令。会话ID不是权限令牌；项目仍只面向本机单用户。完整V4状态规则、有限重确认和核对上限见[归档说明](docs/v4-readme.md)。

重启当前最终验收实例时，在停止原8008实例后设置 `STATE_DB_PATH` 为 `work/sessions-v5-review.sqlite3` 的绝对路径、`LOG_PATH` 为 `work/logs/v5-review.jsonl` 的绝对路径，并运行 `python -m scripts.serve --port 8008`。

## 无凭证练习

```powershell
./.venv/Scripts/python.exe -m scripts.demo_v5 --port 8006
```

打开 [离线演示](http://127.0.0.1:8006/)，页面有明显模拟提示。此模式不加载.env，模型、检索片段、工具和GitHub均为固定模拟，写入只发生在内存假服务中。状态与真实数据隔离。模拟丢失写入响应：

```powershell
./.venv/Scripts/python.exe -m scripts.demo_v5 --port 8007 --mode timeout --folder work/demo-v5-timeout
```

## 检查与验证

```powershell
./.venv/Scripts/python.exe -m scripts.check
./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/my-v5-tests
```

`/health`只报告服务存活与配置标志；`/ready`检查状态库可读、模型key已配置、知识库标记文件存在，不调用外部接口，不证明密钥有效或检索质量。更深入检查通过真实只读任务执行。

日志默认work/logs/events.jsonl，单文件1MB，保留3个旧文件。包含请求ID、路由模板、状态、错误码、耗时和用量；不包含正文、请求查询串、密钥、原始异常。工作台会显示请求ID便于定位。SQLite业务数据会保存用户输入，填写前应脱敏。

可选浏览器验证工具独立安装，不改变运行锁文件，需要已安装Google Chrome：

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements-browser.txt
./.venv/Scripts/python.exe -m scripts.browser_smoke
# 下条会调用真实模型并产生用量，仅执行只读分析；不调用写入确认或执行
./.venv/Scripts/python.exe -m scripts.live_check_v5
```

验证范围与实际结果以docs/v5-validation.md、verification/v5-*为准。没有测吞吐量、P95、跨平台部署或独立新模型准确率，未验证能力不算已实现效果。公开部署所需的用户认证、会话授权与多进程任务队列不在本版范围；支持的部署方式为本机或个人服务器回环地址加SSH隧道。
