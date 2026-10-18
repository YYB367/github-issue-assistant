# V5.1 便捷体验：实际验证记录

## 已执行结果

- 全量 **187 passed**，12条原有Chroma弃用警告；新增15项便捷体验程序案例。原始XML：verification/convenience-full.xml。没有编造性能或效果成绩。
- 原V5的8组浏览器交互回归在0.5.1通过，0页面脚本错误。新记录为convenience-regression-browser.json；原V5浏览器记录和截图从原V5源码包恢复并保留。
- 新便捷界面4组浏览器流程通过：教学结果不调用模型、草稿落在固定主库与自动备份、真实公开案例只读分析、手机布局与保存/备份状态。原始结果convenience-browser.json。
- 三个FastAPI公开Issue及第一页评论，用现有GitHubReader匿名读取均成功，没有发送GitHub token：2582（10条）、1093（3条）、2365（6条）。这些数量是本次第一页返回量，不是完整评论总数。原始记录convenience-public-read.json。
- FastAPI #1093通过真实模型和官方MCP stdio流程完成分析：3次模型调用、2次工具调用，未加载项目知识库，documentation_checked=false。V5.1未导入FastAPI文档，不能把建议当作已验证修复。
- 该公开案例真实分析首次浏览器运行已完成，但手机宽度断言失败；修复CSS后复用已保存的同一分析结果重新验证界面，没有为了布局调试再调用模型。convenience-browser.json明确public_result_reused=true。
- 本次没有发布任何新GitHub评论或标签；公开/教学案例的写入预览被程序返回403。

## 固定数据与真实启动验证

选定主库仍为work/sessions-v5-review.sqlite3，没有改名、复制主库或建立新的版本库。.env固定此绝对路径。更新前12会话、8任务、6操作，逐ID比较确认旧V4/早期V5库的所有业务记录在选定库中完整存在且无差异。更新前另生成protected升级保护备份，见convenience-canonical-data.json。

实际运行Start Issue Assistant.bat完成启动并打开默认浏览器。重复启动复用相同run_id和数据库身份，没有新服务或新数据文件。默认浏览器打开请求返回true，见convenience-launcher.json。

通过私有本地控制入口正常停止托管进程，确认数据库.owner.lock释放；最后自动备份包含停止前全部业务行。再通过实际BAT重新启动后，对sessions/tasks/messages/operations全行排序计算摘要：完全一致，共15会话、11任务、24消息、6操作，见convenience-shutdown-restart.json。这是本次真实进程关闭/重启的验证，区别于V5仅关闭重开lifespan的测试。

真实主库没有执行恢复。恢复、误删恢复、损坏校验、在线恢复拒绝、保留发送历史、异地恢复及写入暂停均在隔离测试库完成。

## 程序案例范围

`tests/test_convenience.py`覆盖：

1. WAL模式下，源连接仍打开时快照包含已提交数据，后续更新不污染快照。
2. 自动备份只保留10份，manual/protected不被自动清理。
3. 恢复前保护当前数据，恢复后暂停GitHub写入。
4. 服务占用锁时拒绝恢复，内容校验不符时拒绝。
5. 恢复会丢失已发送GitHub记录时拒绝回退。
6. 主库误删后恢复。
7. 后台合并连续保存，停止时刷新最后提交。
8. 备份失败不回滚已保存业务数据，不记录原始异常。
9. 旧schema升级前备份。
10. 启动身份拒绝其他库，健康前不打开浏览器。
11. 教学案例无密钥/网络依赖，不伪造模型或MCP调用，写入接口拒绝。
12. 公开案例清空GitHub token、关闭写入与异库知识库，拒绝目标篡改。
13. 停止需私有控制令牌，执行中写入阻止停止，令牌不出现在身份接口与日志。
14. 相对状态路径以项目目录解析。
15. 异地恢复必须显式选择且目标不存在，不能覆盖其他已有库；恢复后仍暂停写入。

## 实际遇到的问题与修正

- 旧演示存在多个状态副本。先比较数据，再固定最完整的原库，不直接选最新文件时间，也不覆盖旧库。
- 8005、8006、旧8008的自有演示进程已停止；8004的旧V4进程被操作系统拒绝终止，保留且不纳入新启动器。不是新的自动审批拒绝；未尝试提权或绕过。后续不要继续使用该旧页面，方便时在原终端关闭。
- 窄屏会话很多时，grid项目的默认min-width让横向列表撑宽整页。给aside设min-width:0、窄屏轨道设minmax(0,1fr)，并限制列表宽度；390px Chrome断言通过。失败截图convenience-mobile-failure.png保留供开发回顾。
- 一次手动验证命令从外层工作区调用-m scripts.launcher，因当前目录错误报No module；更正到项目目录后通过。BAT始终先切到自身目录，用户双击不依赖原工作目录。
- 停机恢复可能丢掉已发送评论的去重记录，因此增加发送历史比较与恢复后写入暂停，而非仅复制回数据库后直接允许写入。

## 限制与未验证内容

- 仍是本机单用户、一个托管主库；没有多用户授权、公开部署或跨设备并发去重。
- 正常使用SQLite保存不等于所有尚未保存编辑可恢复；备份最多恢复到最近成功快照。同盘备份不能覆盖磁盘损坏，需将已完成备份及同名JSON另存外部介质。
- 备份覆盖SQLite业务状态，不备份.env、Embedding模型、Chroma目录；后者保留原准备/重建说明。
- 默认恢复限定当前配置的数据文件；更换磁盘/目录需要明确的--allow-new-location且新目标不存在，之后核对GitHub发送历史。
- GitHub匿名读取受IP配额及网络限制；不会悄悄用个人写token替代公开样例的匿名请求。离线教学案例可用于稳定演示，但不证明模型能力。
- 6个教学案例属于开发演示，不是独立评估集；3个历史公开案例也不构成统计样本。没有宣称检索质量、回答正确率、P95、吞吐量或成本优化提升。
- 只能验证当前Windows/Chrome环境；未测跨平台BAT等价入口、长期磁盘异常、断电或外部存储丢失。

## 官方依据

- [SQLite Connection.backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)：支持源连接仍被访问时生成一致备份。
- [GitHub读取Issue](https://docs.github.com/en/rest/issues/issues#get-an-issue)：公开资源允许未认证访问。
- [GitHub REST限额](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)：匿名主限额按IP计算，通常60次/小时。
