# V2：用当前代码理解知识库与依据

## 固定来源

位置：knowledge/sources.json、ingestion.py::fetch_documents/load_sources。

当前名单只有允许仓库的README，ref是40位commit。GET由固定api.github.com、仓库、白名单文件和ref构建，不使用响应download_url。记录原始UTF-8 SHA256。没有独立INSTALL/FAQ就标记缺失，不虚构项目文档。

测试覆盖固定ref、仿冒download_url、非法路径、仓库、哈希。测试发现曾接受含冒号的URL形路径，已拒绝冒号/query/fragment/空段/父目录段；即使旧代码也不会访问那个URL。

限制：只接收Markdown，单文件128000字节、总400000字节、40个来源、512片段。配置commit不一定等于用户安装版本。

## 切分与实际token

位置：chunking.py::split_markdown、embedding.py::LocalEmbedding.count。

markdown-it-py给出标题、段落、代码块、表格和原始行号。按标题分组并组合完整段落，目标192tokens、最大384。标题前缀重复以保留语境，行号只指正文。完整代码/表格超过192仍可保留；超过384的块或单行明确报错，不自动切断命令。

真实例子：README第24至32行的Node.js20+、npm.cmd install和Copy-Item命令成为同一片段；第38行执行策略说明成为独立片段，分别为真实Issue分析D1/D2。原文反斜线、命令与代码围栏保留。

embedding_tokens由固定配套tokenizer实际计算，不是字符数。当前最大243tokens。encode前再检查384，留在模型512上限以内，避免SDK内部截断。DeepSeek资料预算用cl100k_base估算，与BGE计数不同；真实生成用量以APIusage为准。

## Embedding与距离

位置：embedding.py::prepare_model/LocalEmbedding、store.py::VectorStore/nearest。

固定Qdrant/bge-small-zh-v1.5 revision与5个文件哈希，FastEmbed用CPU ONNX得到512维数组并归一化。变更模型identity会进入另一集合；active清单不一致就拒绝检索，避免混用空间。在线请求不下载权重。

真实报告v2-index-report.json验证512维、最大token与向量范数。单元测试用可预测2维替身检查数据库逻辑；检索评估使用真实512维模型，不能混称为效果验证。

Chroma配置cosine：distance=1-cosine_similarity。Issue #1安装段约0.3177<=0.40，因此保留；只表示向量接近程度。先按仓库、代、类型过滤，再取文档Top3/历史Top2，并过滤超阈值；历史同时排除当前编号。Top3不保证返回3条。

开发6片段基线发现APIKey配置漏召回；细化为10片段并去掉查询前缀改善了Node版本/执行策略，配置仍失败。此后才加入字面关键词回退：仅当文档向量没有达标，2至5个技术词全部匹配，按完整片段长度和稳定位置选择。它没有距离，标keyword/distance=null；没有融合分数或重排序。

独立改写问题仍有两次目标漏召回；ERESOLVE/node-gyp可能召回通用安装段，但不包含具体解法。检索相近和答案有依据是不同的检查。

## 重复入库、更新、删除

位置：store.py::synchronize/active、ingestion.py::save_snapshot、scripts/kb.py。

chunk_id包含仓库、文件、版本、内容哈希、位置、文本、切分版本。同一输入产生同一代，复用已有记录。新版本/删文件产生新代，完整upsert后原子切换active.json，再删旧代；检索只查当前代，FileLock避免查询跨代混合。

实测6片段改为10时新增10、删除6；再次入库新增0、复用10。添加历史后总11片段，旧10条删除。换代未做跨代Embedding缓存，小库优先可读。测试模拟第二批失败，旧代仍可查；重跑复用新代已写的8条、补1条，再清旧代。

清单是知识库管理元数据，不是聊天/任务业务状态。若发布后清理失败可重跑；不是完整跨进程事务框架，SQLite业务状态留待V3。

## 证据与模型

位置：engine.py::retrieve_evidence/generate_analysis/validate_evidence_references/apply_no_evidence_draft。

```mermaid
flowchart LR
  A[模型发起MCP读取] --> B[正文和有限评论]
  B --> C[限定仓库与当前代检索]
  C --> D[完整片段与D1/H1]
  D --> E[模型生成JSON]
  E --> F[schema和引用检查]
  F --> G[分析、来源和草稿]
```

检索在工具循环结束后执行，片段标为不可信外部数据。最终请求没有工具定义，不能因文档指令追加执行。建议提供真实cite_id；D99或仅历史却声称sufficient被拒绝，最多格式修复一次。

引用存在不证明片段支持建议。实测模型把“提供完整报错”引用到安装步骤，也加入离题Inspector建议；人工评估标为关联薄弱，不当成可靠依据。

没有片段时强制insufficient、空recommendations，并用固定资料不足草稿替换模型草稿。原因是JSON合法的模型也曾补充资料外常识；这只保护草稿和建议，其他字段的语义仍要人工审查。

历史最多两页30个原始条目，仅标题/正文，排除PR和超长正文。保留URL、更新时间、“未经验证”标记。当前只有1条模拟报告，分析#1时排除；模拟其他问题时可能召回H1，不能当修复证据。

## 分层验证

程序测试、检索片段支持事实、模型回答依据、操作执行分别记录。没有写入工具，不会向GitHub发布测试内容。失败后的202/204复测标开发回归，新205单独留作验证；首轮失败不被覆盖，程序测试数量不是模型准确率。
