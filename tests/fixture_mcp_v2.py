"""Simulated Issue data for labelled real-embedding/real-model evaluation; never writes GitHub."""
import httpx

from app.config import Settings
from mcp_server.github import GitHubReader
from mcp_server.server import create_server

REPO = "YYB367/learning-mcp-server"
CASES = {
    201: ("PowerShell阻止npm.ps1运行", "Windows PowerShell提示npm.ps1无法加载，因为此系统禁止运行脚本。如何按项目说明安装？"),
    202: ("在哪里填写DeepSeek API Key", "我找不到密钥配置文件，应该在哪个文件配置DeepSeek API Key？请勿索取真实密钥。"),
    203: ("npm install 报ERESOLVE", "安装时出现ERESOLVE dependency tree错误。具体冲突依赖和版本尚未提供，README有确定解决步骤吗？"),
    204: ("太阳系最大行星", "太阳系最大的行星是什么？这个仓库的文档是否能回答？"),
    205: ("是否有鲸鱼寿命的资料", "鲸鱼的寿命有多久？请根据这个仓库文档回答，找不到证据就说明不足。"),
}


def handler(request):
    root = f"/repos/{REPO}"
    if request.url.path == root:
        return httpx.Response(200, json={"private": False})
    if request.url.path.endswith("/comments"):
        return httpx.Response(200, json=[])
    number = int(request.url.path.rsplit("/", 1)[-1])
    title, body = CASES[number]
    return httpx.Response(200, json={"number": number, "title": title, "body": body, "state": "open",
        "labels": [], "comments": 0, "updated_at": "2026-10-14T00:00:00Z"})


if __name__ == "__main__":
    settings = Settings(_env_file=None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    create_server(settings, GitHubReader(settings, client)).run(transport="stdio")
