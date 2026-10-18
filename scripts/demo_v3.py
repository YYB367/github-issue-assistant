"""Two real-model rounds on the user's public test Issue, with labelled simulated input."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description="调用真实GitHub/DeepSeek；两轮分析会使用模型额度。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--output", type=Path, default=Path("verification/v3-live-http.json"))
    args = parser.parse_args()
    report = {"mode":"live", "supplement_is_simulated":True, "events":[]}
    with httpx.Client(base_url=args.base_url, trust_env=False, timeout=15) as client:
        def request(method, path, data=None, expected=200):
            response = client.request(method, path, json=data)
            report["events"].append({"method":method,"path":path,"http_status":response.status_code})
            if response.status_code != expected:
                raise RuntimeError(f"Unexpected status: {response.status_code} at {path}")
            return response.json()

        def run(sid, revision):
            payload = {"expected_revision":revision,"request_key":str(uuid4())}
            task = request("POST", f"/sessions/{sid}/tasks", payload, 202)
            same = request("POST", f"/sessions/{sid}/tasks", payload, 202)
            assert task["task_id"] == same["task_id"]
            deadline = time.monotonic()+110
            while task["status"] == "running" and time.monotonic() < deadline:
                time.sleep(1)
                task = request("GET", f"/sessions/{sid}/tasks/{task['task_id']}")
            report.setdefault("rounds", []).append(task)
            if task["status"] != "completed":
                raise RuntimeError("Analysis did not complete; inspect saved report")
            return request("GET", f"/sessions/{sid}")

        try:
            report["health"] = request("GET", "/health")
            s = request("POST", "/sessions", {"issue_url":"https://github.com/YYB367/learning-mcp-server/issues/1",
                                               "use_knowledge":True}, 201)
            sid = report["session_id"] = s["session_id"]
            s = run(sid, s["revision"])
            s = request("POST", f"/sessions/{sid}/supplements", {"expected_revision":s["revision"],
                "text":"模拟补充（不是实际复现结果）：Windows PowerShell 提示 npm.ps1 无法加载，因为禁止运行脚本。Node.js 22，npm 10。"})
            s = request("PATCH", f"/sessions/{sid}/draft", {"expected_revision":s["revision"],
                "text":"谢谢反馈。请用简短语气，区分文档建议与尚未验证的实际运行结果。"})
            request("PATCH", f"/sessions/{sid}/draft", {"expected_revision":s["revision"]-1,"text":"旧页面内容"}, 409)
            s = run(sid, s["revision"])
            s = request("PATCH", f"/sessions/{sid}/draft", {"expected_revision":s["revision"],
                "text":s["draft"] + "\n（人工备注：此回复尚未发布。）"})
            report["final_session"] = s
            other = request("POST", "/sessions", {"issue_url":s["issue_url"]}, 201)
            request("GET", f"/sessions/{other['session_id']}/tasks/{report['rounds'][0]['task_id']}", expected=404)
            report["checks"] = {"idempotency":True,"stale_edit_rejected":True,"cross_session_task_rejected":True,
                                "draft_saved":s["draft_source"] == "user", "github_writes":False}
        finally:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding="utf-8")
    print(json.dumps({"session_id":sid,"rounds":[r["status"] for r in report["rounds"]],
                      "checks":report["checks"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
