# V1 验证记录

日期：2026-10-12，Asia/Shanghai。实际环境：Windows，Python 3.12.6。此记录描述功能验证，不是模型准确率、性能或成本报告。

## 已执行

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 单元、HTTP、SDK请求格式、真实stdio集成 | 80 passed；0失败、0错误、0跳过 | verification/test-results.xml |
| 独立开发环境依赖一致性 | No broken requirements found | verification/dependency-check.txt |
| 从requirements.lock全新环境安装 | 安装成功；No broken requirements found | verification/clean-install-check.txt；全新环境复跑测试见XML |
| 离线完整演示 | completed；3次成功MCP调用，5次模拟模型请求 | verification/offline-demo.json |
| 真实GitHub/MCP只读检查 | 发现get_issue和list_issue_comments；目标#1返回github_not_found | verification/live-mcp-check.jsonl |
| 用户创建Issue后的真实MCP读取 | 读取真实测试Issue #1；评论第1页为空，未截断 | verification/real-issue-tools.jsonl |
| 真实CLI + DeepSeek（首轮） | completed；2次成功工具调用、3次模型请求 | verification/live-analysis-issue1.json |
| 提示词调整后的真实HTTP + DeepSeek | POST /analyze 返回200/completed；2次成功工具调用、3次模型请求 | verification/live-http-issue1.json |
| 演示服务HTTP检查 | /health、/docs 均200；密钥已配置 | verification/live-http-health.json |
| 真实HTTP接口契约 | health、docs、OpenAPI、成功结构、请求校验和错误码通过 | tests/test_api.py |
| HTTP客户端断连 | ASGI断连取消worker，返回cancelled并关闭工具资源 | tests/test_api.py::test_asgi_disconnect_cancels_worker |
| 凭证隔离 | MCP子进程没有DEEPSEEK_API_KEY；上游错误标记未进入返回/日志 | tests/test_mcp_integration.py、test_llm.py、test_engine.py |

XML内的测试总耗时仅是这一次离线测试执行时间，不表示单次Issue分析延迟或吞吐量。模拟模型的5次请求没有真实token用量，usage为空；没有填造成本数字。

live-mcp-check.jsonl保留用户创建Issue之前的404历史结果，并非最新状态。最新真实数据及分析见新文件，不覆盖失败历史。

测试命令（在项目目录）：

```powershell
python -m pytest -q -p no:cacheprovider --tb=short --junitxml=verification/test-results.xml
python -m pip check
python -X utf8 -m scripts.demo
python -X utf8 -m scripts.check_mcp 'https://github.com/YYB367/learning-mcp-server/issues/1'
```

执行实际使用独立work虚拟环境；安装与重新运行方法见README。pytest关闭缓存是为避开本执行环境的Windows目录权限问题，不改变测试。

## 分层判定

1. 工具调用：检查真实SDK消息、调用ID、目标、执行顺序、分页、边界与失败行为；已通过上述测试。用户创建自己的Issue后，CLI与HTTP均由真实模型产生get_issue、list_issue_comments(page=1)调用，并成功读取GitHub。
2. 检索证据：V1没有检索，未执行也未声称已检索。文档能回答与不能回答的案例留待V2。
3. 回答依据：结构已验证；自己的测试Issue已完成两轮真实输出人工核对，记录如下。仍不能用80项程序测试称为“80/80模型正确”，单个开发案例不能代表独立模型效果。
4. 操作执行：V1无写入工具。程序拒绝模拟模型提出的未知写入操作；添加标签、确认、重复提交和不明确写入恢复留待V4。

## 案例集与真实评估

开发/调参案例在 cases-development.jsonl。最终评估候选在 cases-evaluation.jsonl，均为not_run，issue_url和actual均为空，未用于调整提示词或编造成绩。用户在自己的仓库创建案例后填入实际URL，保存/analyze完整结果，并逐项记录实际行为与判定。

## 自己的测试Issue：真实链路开发验收

目标：https://github.com/YYB367/learning-mcp-server/issues/1（输入fragment被规范化忽略）。正文明确是模拟故障：Windows上npm install失败，缺少Node.js/npm版本、完整报错和复现步骤。GitHub读取是真的，故障本身没有复现。评论数为0，不代表真实多页评论已验收。

| 层次 | 首轮CLI结果 | 调整后HTTP结果 |
|---|---|---|
| 工具执行 | get_issue、list_issue_comments第1页成功 | 同样2次成功调用，目标正确 |
| 结构 | 五项字段通过Pydantic，installation分类 | 同样通过，HTTP 200/completed |
| 已知事实 | Windows、npm install失败、缺信息、无评论均有来源支持 | 同样有支持；没有把示例错误码当作实际报错 |
| 信息不足 | 列出版本、完整报错和复现步骤 | 保留这些关键追问，并明确原因未知 |
| 范围声明 | 未核对文档、未复现、未确认方案 | 同样明确，无写入或已解决声明 |
| 文案缺陷 | 10项追问，末尾让用户忽略测试用例 | 6项追问，去掉忽略测试用例的结尾；仍超过提示词建议的3至5项 |
| 模型请求与报告用量 | 3次；prompt=2970、completion=1724、total=4694 tokens | 3次；prompt=3225、completion=1689、total=4914 tokens |

这些token数是两次接口实际报告值，没有据此推算价格或成本优化。两次请求的耗时只保存在原始JSON，不作为P95/平均性能。

首轮观察被用于调整SYSTEM_PROMPT，因此本Issue属于开发案例D11；第二轮不是独立最终评估，也不能声称这是可靠“准确率”。追问条数通过提示词引导，没有额外添加硬性业务schema限制，文案仍需用户审核。

真实评估请分别记录：

- 工具层：是否确实读取指定Issue与评论；有没有越界或重复执行。
- 依据层：每条已知信息是否由正文/评论支持；是否区分用户陈述、猜测和待验证建议。
- 信息不足：是否追问关键版本、完整报错、命令和复现步骤，是否重复追问已提供信息。
- 输出层：五项结构是否有效，回复是否声称已查文档/已复现/已解决。
- 安全层：外部诱导是否影响自然语言；任何模型提议的越界操作是否被程序拒绝。

当前测试不涉及修改草稿、重复确认、暂停恢复或持久化会话；请求隔离测试仅证明V1独立请求的上下文隔离，不等于已完成V3。

## 未验证与已知缺陷

- 此前仓库为空、密钥未填时未能跑通；用户补齐后，自己的模拟测试Issue完整真实链路已验证。真实评论内容/分页、其他故障、外部诱导指令和独立评估案例仍未真实运行。
- V1资料范围仅是Issue正文和前20条评论；没有项目文档、历史相似Issue或正确性保证。
- 外部内容仍可能诱导模型生成误导性文字。程序边界已验证，模型语义防护尚待独立人工评估。
- 评论页可能在两次请求之间变化，末页满10条时保守提示“可能还有更多”。正文截断可能丢失关键错误。
- 仅支持非思考模式；未验证所有兼容模型/代理的字段支持。最终JSON可能失败，最多修复一次。
- 无全局并发限流、部署鉴权、持久化和实时调用进度；每次请求新建MCP子进程。没有负载与跨平台测试。

V1代码、本地功能验证及自己的单个测试Issue真实端到端验收已完成。保留文案与评估局限，等待用户指定是否进入V2。
