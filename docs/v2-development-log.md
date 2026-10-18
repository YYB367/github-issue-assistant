# V2 开发记录

日期：2026-10-14。继续现有独立项目，两个参考仓库未修改；保留V1源码包和原验证结果。没有GitHub写入。

## 实际发生

- 查询允许仓库当前提交，仍为b4bade195df5ef85bb8cf8af3482538f68e8d67d；文件树只有README文档，没有独立INSTALL/FAQ。
- 独立work/v2-venv安装原锁文件和新增Chroma/FastEmbed/Markdown依赖。准备固定Qdrant ONNX模型revision 46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59及tokenizer/哈希；未修改旧项目虚拟环境或模型缓存。
- 初版384token组合得到6个README片段。向量开发查询能找到Node版本/PowerShell方向，但密钥配置漏召回。
- 比较查询指令前缀与无前缀后，采用无前缀；缩小软目标至192得到10片段。Node/执行策略更聚焦，密钥配置仍未达0.40阈值。
- 只在上述失败分析后增加小型字面关键词回退，不引入混合打分或重排序。要求2至5个技术词全部出现，标keyword/distance=null。配置开发查询现在能召回明确.env来源；独立改写仍有失败。
- 相同README重复入库新增0、复用10；历史索引只发现自己的1条报告，总11片段，旧代10条清除。真实分析#1时该历史条目排除。
- 真实MCP+DeepSeek对Issue #1完成带文档分析；正确引用Node20+和npm.cmd条件说明，证据为partial，未宣称已解决。

## 测试发现与修正

- 来源路径校验最初接受URL形字符串，测试发现后拒绝冒号/query/fragment/空段/父目录段；GET构造始终限定GitHub源。
- 引用ID存在不能证明建议被支持。实际输出出现安装问题中离题的Inspector建议，以及把信息补全请求配到只有安装说明的来源；保留为语义局限。
- 首轮真实模型评估201/203完成，202/204两次格式修复仍失败。失败原始记录不覆盖。
- 增加安全诊断与具体修复反馈，202开发复测显示extra_forbidden，修复后完成；204先违反无证据建议规则，修复后JSON合规却补充了资料外常识。
- 因此在零证据时增加程序的资料不足草稿回退，同时保持insufficient/空建议。其余模型字段仍需人工审核。新205未参与此修复，实际完成并使用正确回退。
- Chroma1.5.9配置检查产生legacy embedding function config的DeprecationWarning，记录为依赖警告，测试及功能未因此失败。
- Windows WMI进程查询权限被拒绝；通过本轮启动日志PID和可读的进程可执行路径核对，仅重启自己创建的V2服务。旧8000/8001服务未终止。

## 验证与风险

115项程序测试通过，pip check无冲突；实际token、512维及归一化记录在v2-index-report.json。程序测试不代表模型准确率。

独立检索E21/E22仍未召回目标事实；E24召回通用安装信息，不能提供node-gyp解法。字面回退可能选到包含词但无目标事实的短片段。有片段时的生成语义未作程序证明，文案依然偏长。

生成token使用cl100k估算，不是DeepSeek精确tokenizer。超长代码块/表格/单行拒绝入库；没有自动复杂代码拆分。同步CPU线程无法被强制中断，取消只停止等待。换代重新Embedding，没有跨代计算缓存。

历史是有限快照，当前只有1条，尚未用真实相似且已核验问题做效果评估。Linux、负载、P95、成本优化及公网部署未验证。

下一步先由用户审阅V2效果与局限，再指定是否进入V3；未实现会话持久化、暂停恢复、写入确认或自动操作。

## 核对的官方资料

- [Chroma集合距离配置](https://docs.trychroma.com/docs/collections/configure)、[Query/Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)、[Upsert](https://docs.trychroma.com/docs/collections/update-data)、[Delete](https://docs.trychroma.com/docs/collections/delete-data)：使用configuration.hnsw.space、query_embeddings、where、upsert/delete；实际锁定1.5.9并检查运行接口。
- [FastEmbed支持模型](https://qdrant.github.io/fastembed/examples/Supported_Models/)、[入门](https://qdrant.github.io/fastembed/Getting%20Started/)、[Qdrant模型来源](https://huggingface.co/Qdrant/bge-small-zh-v1.5)：中文BGE、512维、512输入token的CPU集成；本机0.9.0源码确认specific_model_path/local_files_only参数。
- [markdown-it-py解析API](https://markdown-it-py.readthedocs.io/en/latest/using.html)：block token及map行位置，保留原始Markdown，不渲染不可信HTML。
- 模型生成和MCP SDK用法沿用已经验证的V1官方集成；没有自行实现MCP协议。DeepSeek精确tokenizer没有在本版接入，cl100k计数明确只是估算。
