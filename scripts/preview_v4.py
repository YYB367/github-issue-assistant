"""Prepare two LOCAL previews on the user's test issue. No confirm/execute endpoint is called."""
import json
from pathlib import Path

import httpx


def main():
    report={"github_writes_performed":False,"confirmed":False,"operations":[]}
    body="这是 GitHub Issue 分析助手 V4 的人工确认写入测试。\n本评论仅验证预览、确认、发布与结果记录流程，不代表已定位或修复安装问题。"
    with httpx.Client(base_url="http://127.0.0.1:8004",trust_env=False,timeout=40) as c:
        def request(method,path,data=None):
            r=c.request(method,path,json=data)
            r.raise_for_status()
            return r.json()
        report["health"]=request("GET","/health")
        assert report["health"]["version"]=="0.4.0"
        for kind in ("publish_comment","add_labels"):
            s=request("POST","/sessions",{"issue_url":"https://github.com/YYB367/learning-mcp-server/issues/1","use_knowledge":True})
            sid=s["session_id"]
            if kind=="publish_comment":
                s=request("PATCH",f"/sessions/{sid}/draft",{"expected_revision":s["revision"],"text":body})
            else:
                labels=request("GET",f"/sessions/{sid}/available-labels")
                report["available_labels"]=labels
                assert "question" in labels["labels"]
            op=request("POST",f"/sessions/{sid}/operations/preview",{"expected_revision":s["revision"],
                "kind":kind,"labels":["question"] if kind=="add_labels" else []})
            assert op["status"]=="previewed" and op["attempts"]==0
            report["operations"].append(op)
    output=Path("verification/v4-local-previews.json")
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"github_writes_performed":False,"operations":[{"operation_id":o["operation_id"],
        "session_id":o["session_id"],"target":o["target_url"],"payload":o["payload"],"status":o["status"]} for o in report["operations"]]},ensure_ascii=False))


if __name__=="__main__":
    main()
