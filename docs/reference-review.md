# 已读取的参考实现

读取日期：2026-10-09；本地实现与验证续作日期：2026-10-12。通过只读 GitHub Connector 获取源码，两个原仓库均未修改。没有把它们克隆到新项目目录，也没有读取或复用其本机 `.env`。

## learning-mcp-server

审查快照：`b4bade195df5ef85bb8cf8af3482538f68e8d67d`。

实际读取 [src/index.ts](https://github.com/YYB367/learning-mcp-server/blob/b4bade195df5ef85bb8cf8af3482538f68e8d67d/src/index.ts)、[package.json](https://github.com/YYB367/learning-mcp-server/blob/b4bade195df5ef85bb8cf8af3482538f68e8d67d/package.json)，并取得完整文件树。业务工具实际为 `list_github_issues`，另外有 add/subtract/greet 练习工具。

可借鉴：官方 MCP Server、stdio、Zod 正则和范围校验；api.github.com 固定端点；AbortSignal.timeout(10000)；从 issue 列表过滤 pull_request；错误作为 isError 工具结果；stdout 留给协议。

限制：没有 get_issue 或评论工具；允许任意满足正则的仓库；请求 per_page=100 再筛选、没有继续翻页；正文静默截断到500字符；未限制整个响应的大小；返回 unknown 数据仅作部分检查；没有 Python 应用端的模型工具循环、任务预算或最终分析 schema。

新项目借鉴这些边界思路，使用官方 Python SDK 创建独立服务，以便只维护一种主要语言；未直接沿用原 TypeScript 模块。Python MCP v1 的导入路径与该仓库 TypeScript v2 的路径不相同，不能机械复制。

## langchain-study-assistant

审查快照：`43e93bbbf47bbce50d61e1409c9f8f062ff5d4b7`。

实际读取 [api.py](https://github.com/YYB367/langchain-study-assistant/blob/43e93bbbf47bbce50d61e1409c9f8f062ff5d4b7/src/api.py)、[rag_service.py](https://github.com/YYB367/langchain-study-assistant/blob/43e93bbbf47bbce50d61e1409c9f8f062ff5d4b7/src/rag_service.py)、[05_build_index.py](https://github.com/YYB367/langchain-study-assistant/blob/43e93bbbf47bbce50d61e1409c9f8f062ff5d4b7/src/05_build_index.py)、[run_evaluation.py](https://github.com/YYB367/langchain-study-assistant/blob/43e93bbbf47bbce50d61e1409c9f8f062ff5d4b7/src/run_evaluation.py)、requirements.txt、evaluation.md，并取得完整文件树。审查重点是核心业务与评估代码，不代表逐行读取了所有练习脚本。

可借鉴：Pydantic 的请求/响应模型、FastAPI health 接口、正文与来源共同返回、环境变量密钥、资料不足时拒绝编造、按题保存完整接口结果以便人工复核。

限制：模型名与 base_url 写死，ChatOpenAI.invoke 没有当前项目需要的工具循环；没有全任务超时和操作边界。PDF 入库使用500字符/80字符重叠，缺少稳定内容ID、版本和哈希，没有重复执行去重及旧内容删除。中文 PDF 的距离阈值0.92/1.07是针对该六页资料调参的结果，不能移植到 GitHub 文档；相邻段恢复依赖文本重叠启发式，不能替代 Markdown 标题/代码块切分。评估中的26道题同时用于修复与复测，仓库已明确它们不能代表新资料效果；本项目另保留独立评估案例。

V1 无检索需求，因此没有复制 PDF、Embedding、Chroma 或阈值代码。只借鉴可解释接口与如实记录评估的方式。

## 实施时核对的官方资料

- [MCP Python SDK v1 维护分支](https://py.sdk.modelcontextprotocol.io/v1/)及[客户端示例](https://py.sdk.modelcontextprotocol.io/v1/client/)：ClientSession、stdio_client、initialize/list_tools/call_tool。
- [MCP Server 文档](https://py.sdk.modelcontextprotocol.io/v1/server/)：FastMCP 注册工具和 stdio。
- [DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)：模型只提出调用，应用执行后按 ID 回填。第一次审查成功读取，续作时该页面多次超时；没有把后续失败当作新核对成功。
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)：json_object、明确 JSON 格式示例、输出长度与空内容处理。
- [官方 OpenAI Python SDK](https://developers.openai.com/api/reference/python)：AsyncOpenAI、base_url、关闭自动重试；本机源码与请求格式测试确认了此锁定版本使用 HTTPX2。
- [GitHub Issue API](https://docs.github.com/en/rest/issues/issues#get-an-issue)、[评论 API](https://docs.github.com/en/rest/issues/comments#list-issue-comments)：PR 也可能来自 Issue 端点，评论分页及公开资源只读访问。
- [FastAPI 请求体](https://fastapi.tiangolo.com/tutorial/body/)：Pydantic 校验与生成 OpenAPI。

文档没有替代实际版本验证。requirements.lock 来自独立环境的 pip freeze，pip check 和本项目测试均已执行。未验证的外部模型行为单独留在验证记录。
