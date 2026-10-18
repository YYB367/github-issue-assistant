# GitHub Issue 分析与处理助手 — V2

提交允许仓库的Issue链接，模型通过真实MCP读取正文和评论，应用检索固定版本项目资料，生成带引用的处理建议和回复草稿。返回工具轨迹、片段、来源行号/提交/哈希、检索距离及证据充分性。

当前仓库：YYB367/learning-mcp-server。知识源是提交b4bade195df5ef85bb8cf8af3482538f68e8d67d的README；该提交没有独立安装说明或FAQ。建议不代表已复现、已修复或已验证方案。真实检索和模型评估仍有失败案例，见[V2验证记录](v2-validation.md)。

## 目录与职责

| 位置 | 职责 |
|---|---|
| app/schemas.py、app/engine.py | 结构化结果、原有工具循环、检索、模型生成、引用校验 |
| app/api.py、app/cli.py | /analyze、/knowledge/search、/health、命令行 |
| app/llm.py、app/mcp_client.py、mcp_server/ | 官方SDK、DeepSeek兼容接口、MCP和GitHub只读工具 |
| knowledge/sources.json、ingestion.py | 固定提交/文件名单、下载、哈希、有限历史快照 |
| knowledge/chunking.py、embedding.py | Markdown切分、实际Embedding token计数、固定CPU模型 |
| knowledge/store.py、retrieval.py | Chroma、完整代发布、旧内容清理、检索与上下文预算 |
| scripts/kb.py、evaluate_v2.py | 管理命令、开发与独立评估记录 |
| tests/、verification/、docs/ | 测试、实际结果、教学与开发记录 |

## 安装

实际验证Windows、Python3.12.6。依赖版本在requirements.lock精确锁定。V2沿用原SDK，新增Chroma1.5.9、FastEmbed0.9.0、markdown-it-py4.0.0等本地依赖。FastEmbed使用中文BGE小模型的CPU ONNX权重，512维；应用自己运行推理。

在项目目录执行：

```powershell
& 'D:\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

其他电脑使用自己的Python3.12解释器。已填写的.env无需覆盖。当前新增配置默认值如下：

```dotenv
KNOWLEDGE_ENABLED=true
RETRIEVAL_TOP_K=3
RETRIEVAL_MAX_DISTANCE=0.40
HISTORY_TOP_K=2
HISTORY_MAX_DISTANCE=0.30
KEYWORD_FALLBACK_ENABLED=true
```

原有ALLOWED_REPOSITORY、DEEPSEEK_API_KEY/MODEL/BASE_URL、GITHUB_TOKEN、调用与时间预算仍有效。密钥仅保存在本机.env，不进入模型上下文、MCP返回或日志。GitHub token可以为空。程序支持受信任代理环境变量，不关闭TLS验证。

## 准备知识库

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.kb prepare-model
.\.venv\Scripts\python.exe -X utf8 -m scripts.kb sync-docs
.\.venv\Scripts\python.exe -X utf8 -m scripts.kb status
```

prepare-model明确下载固定提交的公开权重和tokenizer、记录SHA256。在线请求只使用已准备的本地文件。模型源Qdrant/bge-small-zh-v1.5的revision记录在embedding.py；默认运行数据在项目work/models及work/knowledge，源码包不含模型/数据库。

sync-docs只读取sources.json中的Markdown名单。改文件列表或固定commit后重跑，可更新来源和删除旧文件。相同输入复用同代记录，不重复Embedding。新代完整写入后，原子切换active.json，再清理旧代；中断的新代不会发布。检索与入库有文件锁，避免混合版本。

当前README为10片段。可选历史索引：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.kb sync-history --limit 20
```

最多两页、30个原始列表条目，排除PR，保留最多30条报告；超长正文跳过，可能少于limit。只索引标题/正文，不索引评论，保留URL/更新时间，分析时排除当前Issue。历史内容标为未经验证，关闭状态不代表已解决。当前仓库只有1条历史报告。

## 启动与演示

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8002
```

当前工作区V2界面：[http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs)。8000/8001可能是以前的服务；health.version应为0.2.0。配置/代码/依赖更改后重启自己的服务。

先用POST /knowledge/search独立检查证据，不调用DeepSeek：

```json
{"query":"PowerShell提示npm.ps1无法加载，执行策略阻止npm怎么办？","exclude_issue":1}
```

再用POST /analyze提交真实测试Issue：

```json
{"issue_url":"https://github.com/YYB367/learning-mcp-server/issues/1","use_knowledge":true}
```

检查status/error，再看analysis.recommendations[].evidence_ids，以及retrieval.evidence[].cite_id/text/url/distance/retrieval_method。用D1等编号找到真实片段，点击固定提交和行号核对。use_knowledge=false可明确比较V1流程，不改变全局设置。

CLI：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.cli 'https://github.com/YYB367/learning-mcp-server/issues/1'
.\.venv\Scripts\python.exe -X utf8 -m app.cli 'https://github.com/YYB367/learning-mcp-server/issues/1' --without-knowledge
```

Issue #1故障是用户模拟场景，GitHub与DeepSeek调用是真实的，并不代表复现了真实缺陷。其他模拟Issue评估在结果中明确标simulated；MCP、Chroma、Embedding和模型请求是真实执行，不向GitHub创建测试内容。

## 输出与边界

基础分析：summary/category/known_information/missing_information/reply_draft。V2新增evidence_status（sufficient/partial/insufficient）和recommendations，每条含text及evidence_ids。

程序验证引用ID存在；没有片段时必须insufficient、空recommendations，并把用户可用草稿替换为程序的资料不足说明。其他模型字段仍需人工审核。历史报告不能单独支撑sufficient。格式/引用不合法时最多修复一次，output_validation_errors只记录安全错误类型与字段，不记录非法原文。

documentation_checked=true表示文档片段已交给模型，不表示读完文档、验证事实或解决方案正确。检索命中也不证明证据充分。

向量基线：归一化512维向量，Chroma显式cosine距离，distance=1-cosine_similarity，越小越接近。文档Top3、阈值<=0.40；历史Top2、阈值<=0.30。它们是开发基线，不表示概率，不移植旧PDF阈值。

开发发现密钥配置漏召回后，才加入关键词回退：仅在文档向量没有过阈值时启用，要求2至5个技术词全部出现。回退标keyword、distance=null，未混合分数或重排序；这条简易规则仍可能选错片段。

Markdown按标题/段落组合，软目标192tokens，硬上限384是配套tokenizer实际计数。完整代码块/表格可超过软目标；超过硬上限的代码、表格、单行明确拒绝，需人工拆分。重复标题提供上下文，行号标示正文位置。

资料列表最多16000字节、cl100k_base估算2200tokens；此估算不是DeepSeek精确计数。全消息仍受100000字节上限和模型输出预算限制，真实用量以usage为准。原有6次工具调用、8次模型请求、90秒任务预算、20条评论上限和取消处理保留。

知识库未准备返回503；失败不返回成功分析。同步CPU检索通过线程执行，取消停止等待，但不能强行中断已进入原生推理的线程。

## 验证和已知限制

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -X utf8 -m scripts.evaluate_v2
# 下面使用真实DeepSeek与模拟Issue，会消耗模型用量：
.\.venv\Scripts\python.exe -X utf8 -m scripts.evaluate_v2 --model-cases 201 202 203 204
```

调参后的复测标development_regression，不能算新独立评估。当前独立检索集保留两个漏召回；模型首轮保留两个失败。结构和引用ID校验无法证明语义依据，实际仍有泛化追问、离题Inspector建议、引用关联薄弱等问题。

[V2教学](v2-teaching.md)、[V2开发记录](v2-development-log.md)、[V2验证](v2-validation.md)包含实际证据。V1记录保存在docs/v1-readme.md、docs/validation.md和旧验证文件。

下一版建议为V3的SQLite业务状态与补充信息流程；是否进入下一版由用户指定。
