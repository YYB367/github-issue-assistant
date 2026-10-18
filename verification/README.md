# 本地验证输出

此目录保存演示脚本和测试生成的原始结果。原始文件可能包含本机路径、会话内容、操作标识和截图，因此不随 Git 提交；已有文件仍保留在开发机器。

仓库中的当前验证摘要见 [验证记录](../docs/validation-summary.md)。历史开发文档提到的 `verification/*.json`、XML 和截图是当时的本地证据路径，不能假定克隆仓库后存在。

在项目目录可重新运行不需要模型密钥或 GitHub 写权限的程序测试：

```powershell
./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/github-tests --junitxml=verification/github-tests.xml
```

该测试集包含真实 MCP stdio 进程通信及模拟上游的异常测试；模拟结果不能作为真实模型效果成绩。需要真实服务的演示脚本应先阅读脚本说明，单独准备凭证与目标，并区分真实读取、模拟数据和人工授权写入。
