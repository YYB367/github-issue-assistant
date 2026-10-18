"""Deterministic HTTP/state demo using a fake GitHub transport; never writes to GitHub."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_operations import FakeGitHub, client, preview, confirm, execute


def main():
    folder=Path("work")
    folder.mkdir(exist_ok=True)
    report={"mode":"offline_demo","github_network_calls":False,"scenarios":[]}
    for kind,mode,labels in [("publish_comment","ok",[]),("add_labels","ok",["help wanted"]),
                             ("publish_comment","timeout",[])]:
        with TemporaryDirectory(prefix="v4-demo-",dir=folder) as tmp:
            fake=FakeGitHub(mode)
            with client(Path(tmp),fake) as c:
                sid,op=preview(c,kind,labels=labels)
                confirm(c,sid,op)
                result=execute(c,sid,op)
                repeated=execute(c,sid,op)
                scenario={"kind":kind,"transport_mode":mode,"preview":op,"result":result,
                          "repeated_status":repeated["status"],"post_count_after_repeat":fake.posts}
                if mode=="timeout":
                    scenario["recovered"]=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/reconcile",json={}).json()
                scenario["final_post_count"]=fake.posts
                assert fake.posts==1
                report["scenarios"].append(scenario)
    output=Path("verification/v4-offline-demo.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"mode":report["mode"],"scenarios":[{"kind":s["kind"],"status":s["result"]["status"],
        "recovered_status":s.get("recovered",{}).get("status"),"post_count":s["final_post_count"]} for s in report["scenarios"]]},ensure_ascii=False))


if __name__=="__main__":
    main()
