# V2 实际验证记录

2026-10-14，Windows/Python3.12.6。分别检查工具、检索、回答依据和操作边界；不把它们合并为准确率。

## 程序与索引

| 检查 | 实际结果 | 原始证据 |
|---|---|---|
| 全部程序测试 | 115 passed，0失败/错误/跳过；12个Chroma弃用警告 | verification/v2-test-results.xml |
| 依赖一致性 | No broken requirements found | verification/v2-dependency-check.txt |
| 同代重复README入库 | 新增0、复用10、删除0 | verification/v2-repeat-ingestion.json |
| 有限历史入库 | 1条报告，11片段，删除旧代10条 | verification/v2-history-ingestion.json |
| 向量和token检查 | 512维，最大243实际Embedding tokens，范数偏差约8.22e-8 | verification/v2-index-report.json |
| 原始知识快照 | 固定README提交、内容哈希、历史更新时间 | verification/v2-corpus-snapshot.json |
| 真实Issue #1的CLI分析 | completed，2次MCP成功调用、3次模型请求，partial | verification/v2-live-issue1.json |
| 最新HTTP与搜索接口 | 见实际HTTP状态、来源、分析结果 | verification/v2-live-http.json |

支持的程序边界包括：unsafe路径、仓库/hash/model不一致、代码块token超限、重复入库、删除来源、分批失败不发布、持久化重开、向量阈值、预算整体省略、当前Issue排除、历史非权威、显式关键词标签、未知引用拒绝、零证据回退、HTTP opt-out及未准备503。原V1超时/取消/隔离测试仍保留。

## 检索基线及开发

文档cosine Top3、阈值0.40；历史Top2、0.30。来源先按仓库和active generation过滤；距离越小越接近，不是解决概率。

| 开发问题 | 初版6片段/有查询前缀 | 改为10片段/无前缀 | 随后字面回退 |
|---|---|---|---|
| Node版本与安装 | 安装段0.3823，排名第2 | 安装段0.2904，排名第1 | 保持向量 |
| PowerShell执行策略 | 安装段0.3847 | 独立执行策略段0.2906 | 保持向量 |
| 配置DeepSeek API Key | 无过阈值片段 | 仍无过阈值片段 | 全部技术词匹配到.env说明 |
| 具体ERESOLVE冲突 | 无过阈值片段 | 通用PowerShell段0.3734 | 有召回但并非具体冲突解法 |
| 太阳系问题 | 无片段 | 无片段 | 无片段 |

这些数值来自实际调试输出；不能用同一开发问题的复测作为独立成绩。最后的开发对照和独立结果在verification/v2-retrieval-evaluation.json。

## 独立检索检查

knowledge/evaluation-cases.json中的确切改写问题未用于挑选切分/前缀/阈值。执行一次后保留原结果，没有按失败再次调这些规则。listed_facts_present仅机械检查指定文本是否存在，不代表回答正确性。

| 案例 | 实际结果 | 判定范围 |
|---|---|---|
| E20 Node最低版本和安装命令 | 找到L24-32，指定事实在片段中 | 检索支持目标事实 |
| E21 脚本限制改写 | 仅召回“已知限制”，没有npm.cmd事实 | 目标漏召回 |
| E22 Continue凭证文件改写 | 回退选了三个含词短片段，没有.env事实 | 目标漏召回，回退排序局限 |
| E23 Chroma损坏恢复 | 无片段 | 没有项目证据 |
| E24 node-gyp编译工具 | 通用安装/Inspector片段 | 不支持具体编译问题解法 |

没有虚构召回率或总体准确率。E21/E22是已知失败；下一次优化需使用新的开发案例和新独立集。

## 真实模型与模拟Issue评估

tests/fixture_mcp_v2.py中的Issue数据是模拟的，MCP进程/Embedding/Chroma/DeepSeek是真的。不存在对应GitHub写入。结果mode=offline_demo并有清楚标记，不能当成线上Issue成功。

| 首轮案例 | 技术结果 | 回答/依据观察 |
|---|---|---|
| 201 明确npm.ps1策略阻止 | completed、partial | npm.cmd建议引用L38；附带安装/Inspector步骤偏多；历史H1被注明未验证 |
| 202 密钥文件 | failed/model_invalid_result | 两次输出校验失败，拒绝给成功分析 |
| 203 ERESOLVE缺依赖版本 | completed、partial | 明确片段没有具体ERESOLVE解法，不给确定结论；部分泛化建议引用关联薄弱 |
| 204 项目外问题 | failed/model_invalid_result | 无证据时拒绝不合法输出 |

原始首轮保存在verification/v2-model-evaluation.json，没有覆盖成成功结果。

之后的202/204是development_regression（verification/v2-model-regressions.json）。加入具体安全错误反馈后，202先extra_forbidden再修复成功；204先无证据却有建议，修复后结构正确，但草稿补充了资料外常识。这证明schema/ID校验不等于语义依据校验。

此后零证据草稿改为程序回退。新205鲸鱼寿命问题未用于该修改，保存在verification/v2-model-holdout.json：completed、insufficient、0片段、空建议，草稿为程序提供的资料不足说明；第一次模型仍违反无证据建议规则，具体反馈后修复一次。不能把这一次成功当成稳定性或全量语义安全保证。

真实线上Issue #1只报告Windows安装失败、缺版本/报错/复现信息，评论为空。CLI正确引用Node20+和有条件npm.cmd说明，partial；没有确认错误根因。建议2的“补充完整报错”引用支持较弱，Inspector建议离题，文案仍较长。这是开发案例，未算进独立模型成绩。

## 尚未验证

- 文档仅固定README，独立安装/FAQ不存在；版本不一定匹配用户本地。
- 引用ID存在不证明命题被支持；只有草稿零证据分支有程序固定说明，其他字段和有证据的建议仍需人工审核。
- 有限历史快照只有1条模拟报告，真实历史回复质量及多页相似问题效果未验证。
- 未做重排序、融合排名、负载/跨平台测试或成本优化；记录里的elapsed_ms和usage只代表实际单次运行。
- 原有纯V1记录仍在docs/validation.md；V3状态、V4确认写入、V5部署未实现。
