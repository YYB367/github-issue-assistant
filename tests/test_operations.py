import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.github_write import GitHubWriter,WriteError
from app.operation_store import OperationStore
from app.schemas import parse_issue_url
from app.state import StateStore,StateError
from tests.helpers import config,URL,REPO


class FakeGitHub:
    def __init__(self,mode="ok"):
        self.mode=mode
        self.requests=[]
        self.comments=[]
        self.labels=[]
        self.posts=0

    def handle(self,r):
        self.requests.append((r.method,str(r.url)))
        assert r.url.host=="api.github.com"
        assert r.headers["Authorization"]=="Bearer test-only-token"
        path=r.url.path
        prefix=f"/repos/{REPO}"
        if r.method=="POST":
            self.posts+=1
            if self.mode in ("403","422"):
                return httpx.Response(int(self.mode),json={})
            payload=json.loads(r.content)
            if path.endswith("/comments"):
                data={"id":101,"body":payload["body"],"user":{"id":7},
                      "issue_url":"https://api.github.com"+prefix+"/issues/1"}
                self.comments.append(data)
            else:
                self.labels=sorted(set(self.labels+payload["labels"]))
                data=[{"name":name} for name in self.labels]
            if self.mode=="timeout":
                raise httpx.ReadTimeout("simulated lost response",request=r)
            if self.mode=="500":
                return httpx.Response(500,json={})
            if self.mode=="invalid_json":
                return httpx.Response(201,content=b"not json")
            if self.mode=="wrong_body":
                data={**data,"body":"different"}
            if self.mode=="redirect":
                return httpx.Response(307,headers={"Location":"https://evil.test"})
            return httpx.Response(201 if path.endswith("comments") else 200,json=data)
        if path=="/user":
            if self.mode=="preflight_timeout":
                raise httpx.ReadTimeout("preflight timed out",request=r)
            return httpx.Response(200,json={"id":7,"login":"tester"})
        if path==prefix:
            return httpx.Response(200,json={"full_name":REPO,"private":self.mode=="private",
                "permissions":{"push":self.mode!="denied"},"archived":self.mode=="archived"})
        if path==prefix+"/issues/1":
            data={"number":1,"locked":self.mode=="locked"}
            if self.mode=="pr":
                data["pull_request"]={}
            return httpx.Response(200,json=data)
        if path==prefix+"/labels":
            return httpx.Response(200,json=[{"name":"bug"},{"name":"help wanted"}])
        if path.startswith(prefix+"/labels/"):
            name=path.rsplit("/",1)[-1]
            return httpx.Response(200,json={"name":name}) if name in ("bug","help wanted") else httpx.Response(404,json={})
        if path==prefix+"/issues/1/labels":
            return httpx.Response(200,json=[{"name":name} for name in self.labels])
        if path==prefix+"/issues/1/comments":
            return httpx.Response(200,json=self.comments)
        if path.startswith(prefix+"/issues/comments/"):
            return httpx.Response(200,json=self.comments[0] if self.comments else {})
        raise AssertionError(path)

    def factory(self,settings,unused_client):
        return GitHubWriter(settings,httpx.AsyncClient(transport=httpx.MockTransport(self.handle)))


def client(tmp_path,fake,enabled=True):
    return TestClient(create_app(config(state_db_path=tmp_path/"s.db",github_token="test-only-token",
        github_writes_enabled=enabled),writer_factory=fake.factory))


def preview(c,kind="publish_comment",draft="V4模拟测试，请勿当作实际修复。",labels=None):
    s=c.post("/sessions",json={"issue_url":URL}).json()
    sid=s["session_id"]
    s=c.patch(f"/sessions/{sid}/draft",json={"expected_revision":1,"text":draft}).json()
    response=c.post(f"/sessions/{sid}/operations/preview",json={"expected_revision":s["revision"],"kind":kind,"labels":labels or []})
    assert response.status_code==201,response.text
    return sid,response.json()


def confirm(c,sid,op):
    r=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/confirm",
        json={"content_hash":op["content_hash"],"confirmation_text":op["confirmation_text"]})
    assert r.status_code==200,r.text
    return r.json()


def execute(c,sid,op):
    path=f"/sessions/{sid}/operations/{op['operation_id']}"
    response=c.post(path+"/execute")
    assert response.status_code==202,response.text
    for _ in range(100):
        result=c.get(path).json()
        if result["status"]!="executing":
            return result
        time.sleep(.01)
    pytest.fail("write did not finish")


@pytest.mark.parametrize("kind,labels",[("publish_comment",[]),("add_labels",["bug","help wanted"])])
def test_confirmed_write_and_duplicate_execution(tmp_path,kind,labels):
    fake=FakeGitHub()
    fake.labels=["existing-label"]
    with client(tmp_path,fake) as c:
        sid,op=preview(c,kind,labels=labels)
        assert fake.posts==0 and op["status"]=="previewed"
        if kind=="publish_comment":
            assert op["operation_id"] in op["payload"]["body"]
        assert c.post(f"/sessions/{sid}/operations/{op['operation_id']}/execute").status_code==409
        confirm(c,sid,op)
        confirm(c,sid,op)
        result=execute(c,sid,op)
        assert result["status"]=="succeeded" and result["attempts"]==1
        assert execute(c,sid,op)["status"]=="succeeded" and fake.posts==1
        assert result["actor"]["id"]==7
        if kind=="add_labels":
            assert "existing-label" in fake.labels
        assert c.get(f"/sessions/{sid}").json()["operation_status"]=="succeeded"
        assert c.get(f"/sessions/{sid}/available-labels").json()["labels"]==["bug","help wanted"]


def test_confirm_content_binding_edit_invalidation_and_cancel(tmp_path):
    fake=FakeGitHub()
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        path=f"/sessions/{sid}/operations/{op['operation_id']}"
        assert c.post(path+"/confirm",json={"content_hash":"0"*64,"confirmation_text":op["confirmation_text"]}).status_code==409
        assert c.post(path+"/confirm",json={"content_hash":op["content_hash"],"confirmation_text":"yes"}).status_code==409
        confirm(c,sid,op)
        s=c.get(f"/sessions/{sid}").json()
        c.patch(f"/sessions/{sid}/draft",json={"expected_revision":s["revision"],"text":"changed"}).raise_for_status()
        assert c.get(path).json()["status"]=="invalidated"
        assert c.post(path+"/execute").status_code==409 and fake.posts==0
        s=c.get(f"/sessions/{sid}").json()
        new=c.post(f"/sessions/{sid}/operations/preview",json={"expected_revision":s["revision"],"kind":"publish_comment"}).json()
        confirm(c,sid,new)
        cancel=f"/sessions/{sid}/operations/{new['operation_id']}/cancel"
        assert c.post(cancel).json()["status"]=="cancelled"
        assert c.post(cancel).json()["status"]=="cancelled"
        assert c.post(cancel.replace("/cancel","/execute")).status_code==409


@pytest.mark.parametrize("mode,expected",[("denied","repository_write_permission_required"),("pr","pull_request"),
    ("private","repository_not_public"),("locked","issue_locked"),("archived","repository_read_only"),
    ("preflight_timeout","github_timeout")])
def test_remote_preflight_blocks_before_post(tmp_path,mode,expected):
    fake=FakeGitHub(mode)
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        result=execute(c,sid,op)
        assert result["status"]=="failed" and result["error_code"]==expected and fake.posts==0


def test_missing_label_never_created(tmp_path):
    fake=FakeGitHub()
    with client(tmp_path,fake) as c:
        sid,op=preview(c,"add_labels",labels=["not-existing"])
        confirm(c,sid,op)
        result=execute(c,sid,op)
        assert result["status"]=="failed" and fake.posts==0


@pytest.mark.parametrize("mode",["timeout","500","invalid_json","wrong_body","redirect"])
def test_ambiguous_comment_read_only_recovery(tmp_path,mode):
    fake=FakeGitHub(mode)
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        result=execute(c,sid,op)
        assert result["status"]=="unknown" and fake.posts==1
        assert execute(c,sid,op)["status"]=="unknown" and fake.posts==1
        recovered=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/reconcile",json={}).json()
        assert recovered["status"]=="succeeded" and fake.posts==1
        assert recovered["result"]["comment_id"]==101
        assert all("evil.test" not in url for _,url in fake.requests)


def test_unknown_absence_wrong_author_target_body_do_not_allow_retry(tmp_path):
    fake=FakeGitHub("timeout")
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        execute(c,sid,op)
        original=fake.comments[0].copy()
        for altered in ({**original,"user":{"id":8}}, {**original,"issue_url":"https://api.github.com/repos/other/repo/issues/1"},
                        {**original,"body":"different"}):
            fake.comments=[altered]
            r=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/reconcile",json={"comment_id":101})
            assert r.json()["status"]=="unknown"
        fake.comments=[]
        assert c.post(f"/sessions/{sid}/operations/{op['operation_id']}/reconcile",json={}).json()["status"]=="unknown"
        s=c.get(f"/sessions/{sid}").json()
        s=c.patch(f"/sessions/{sid}/draft",json={"expected_revision":s["revision"],"text":"changed draft"}).json()
        assert c.post(f"/sessions/{sid}/operations/preview",json={"expected_revision":s["revision"],"kind":"publish_comment"}).status_code==409
        assert fake.posts==1


def test_labels_unknown_reconciles_state(tmp_path):
    fake=FakeGitHub("timeout")
    with client(tmp_path,fake) as c:
        sid,op=preview(c,"add_labels",labels=["bug"])
        confirm(c,sid,op)
        assert execute(c,sid,op)["status"]=="unknown"
        result=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/reconcile",json={}).json()
        assert result["status"]=="succeeded" and fake.posts==1


@pytest.mark.parametrize("mode",["403","422"])
def test_explicit_rejection_never_automatically_retries(tmp_path,mode):
    fake=FakeGitHub(mode)
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        assert execute(c,sid,op)["status"]=="failed"
        assert c.post(f"/sessions/{sid}/operations/{op['operation_id']}/execute").status_code==409
        assert fake.posts==1


def test_disabled_cross_session_and_browser_origin(tmp_path):
    fake=FakeGitHub()
    with client(tmp_path,fake,False) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        assert c.post(f"/sessions/{sid}/operations/{op['operation_id']}/execute").status_code==403
        other=c.post("/sessions",json={"issue_url":URL}).json()["session_id"]
        assert c.get(f"/sessions/{other}/operations/{op['operation_id']}").status_code==404
        assert c.post("/sessions",json={"issue_url":URL},headers={"Origin":"https://evil.test"}).status_code==403
        assert c.get("/health",headers={"Host":"evil.test"}).status_code==400
        assert fake.posts==0


def setup_store(tmp_path):
    state=StateStore(tmp_path/"s.db")
    s=state.create(parse_issue_url(URL,REPO),False)
    s=state.edit(s["session_id"],1,"draft","draft")
    ops=OperationStore(state)
    op=ops.preview(s["session_id"],s["revision"],"publish_comment",[])
    ops.confirm(s["session_id"],op["operation_id"],op["content_hash"],op["confirmation_text"])
    return state,ops,s,op


def test_atomic_claim_single_dispatch_and_block_edit(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    sid,oid=s["session_id"],op["operation_id"]
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:ops.claim(sid,oid)[1],range(2)))
    assert sorted(results)==[False,True]
    with pytest.raises(StateError) as e:
        state.edit(sid,s["revision"],"edit during dispatch","draft")
    assert e.value.code=="operation_executing"
    ops.dispatched(sid,oid,{"id":7})
    with pytest.raises(StateError):
        ops.dispatched(sid,oid,{"id":7})


@pytest.mark.parametrize("dispatched,status",[(False,"failed"),(True,"unknown")])
def test_restart_distinguishes_dispatch_intent(tmp_path,dispatched,status):
    state,ops,s,op=setup_store(tmp_path)
    sid,oid=s["session_id"],op["operation_id"]
    ops.claim(sid,oid)
    if dispatched:
        ops.dispatched(sid,oid,{"id":7})
    restarted=OperationStore(StateStore(tmp_path/"s.db"))
    restarted.recover()
    assert restarted.get(sid,oid)["status"]==status
    assert restarted.get(sid,oid)["error_code"]=="server_interrupted"


def test_expiry_target_change_and_analysis_invalidate_confirmation(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    sid,oid=s["session_id"],op["operation_id"]
    op=ops.get(sid,oid)
    with state.transaction() as db:
        op["expires_at"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        db.execute("UPDATE operations SET data=? WHERE id=?",(json.dumps(op),oid))
    with pytest.raises(StateError) as e:
        ops.claim(sid,oid)
    assert e.value.code=="confirmation_expired"
    state.start(sid,s["revision"],"analysis")
    assert ops.get(sid,oid)["status"]=="invalidated"


def test_duplicate_across_sessions(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    ops.claim(s["session_id"],op["operation_id"])
    ops.complete(s["session_id"],op["operation_id"],"succeeded",{"comment_id":1})
    other=state.create(parse_issue_url(URL,REPO),False)
    other=state.edit(other["session_id"],1,"draft","draft")
    with pytest.raises(StateError) as e:
        ops.preview(other["session_id"],other["revision"],"publish_comment",[])
    assert e.value.code=="duplicate_completed_operation"


@pytest.mark.parametrize("payload",[
    {"kind":"publish_comment","body":"model-chosen-body"},
    {"kind":"add_labels","labels":[]},
    {"kind":"add_labels","labels":["bug","bug"]},
    {"kind":"publish_comment","labels":["bug"]},
    {"kind":"close_issue"},
])
def test_only_supported_explicit_parameters(tmp_path,payload):
    fake=FakeGitHub()
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        assert c.post(f"/sessions/{sid}/operations/preview",json={"expected_revision":2,**payload}).status_code==422
        assert fake.posts==0


def test_operation_limit_and_current_target_check(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    sid=s["session_id"]
    with state.transaction() as db:
        changed=state._session(db,sid)
        changed["target"]["issue_number"]=2
        db.execute("UPDATE sessions SET data=? WHERE id=?",(json.dumps(changed),sid))
    with pytest.raises(StateError) as e:
        ops.claim(sid,op["operation_id"])
    assert e.value.code=="operation_target_changed"
    with state.transaction() as db:
        changed["target"]["issue_number"]=1
        db.execute("UPDATE sessions SET data=? WHERE id=?",(json.dumps(changed),sid))
    for i in range(49):
        s=state.edit(sid,s["revision"],f"draft {i}","draft")
        ops.preview(sid,s["revision"],"publish_comment",[])
    s=state.edit(sid,s["revision"],"51st","draft")
    with pytest.raises(StateError) as e:
        ops.preview(sid,s["revision"],"publish_comment",[])
    assert e.value.code=="operation_limit"


async def test_reconciliation_pagination_bound_and_second_precision(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    op["actor"]={"id":7}
    requests=[]
    def handler(r):
        requests.append(r)
        if r.url.path==f"/repos/{REPO}":
            return httpx.Response(200,json={"private":False,"full_name":REPO})
        return httpx.Response(200,json=[{"id":i+1,"body":"unrelated"} for i in range(100)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await GitHubWriter(config(),c).reconcile(op) is None
    assert len(requests)==4
    assert [r.url.params['page'] for r in requests[1:]]==['1','2','3']
    assert requests[-1].url.params['since'].endswith('Z')
    assert '.' not in requests[-1].url.params['since']


def test_old_database_additive_migration_preserves_sessions(tmp_path):
    import sqlite3
    path=tmp_path/'old.db'
    data={"session_id":"old","draft":"user data"}
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO sessions VALUES(?,?)",('old',json.dumps(data)))
        db.execute("PRAGMA user_version=1")
    state=StateStore(path)
    with state.transaction() as db:
        assert json.loads(db.execute("SELECT data FROM sessions WHERE id='old'").fetchone()[0])==data
        assert db.execute("PRAGMA user_version").fetchone()[0]==2


def test_missing_token_and_changed_repository_never_dispatch(tmp_path):
    fake=FakeGitHub()
    settings=config(state_db_path=tmp_path/'s.db',github_writes_enabled=True)
    app=create_app(settings,writer_factory=fake.factory)
    with TestClient(app) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        path=f"/sessions/{sid}/operations/{op['operation_id']}/execute"
        assert c.post(path).status_code==503
        app.state.settings.allowed_repository='other/repo'
        assert c.post(path).status_code==403
        assert fake.posts==0


def test_permission_correction_explicit_retry_keeps_exact_content(tmp_path):
    fake=FakeGitHub('403')
    with client(tmp_path,fake) as c:
        sid,op=preview(c)
        confirm(c,sid,op)
        assert execute(c,sid,op)['status']=='failed'
        path=f"/sessions/{sid}/operations/{op['operation_id']}"
        ordinary={'content_hash':op['content_hash'],'confirmation_text':op['confirmation_text']}
        assert c.post(path+'/confirm',json=ordinary).status_code==409
        retry={**ordinary,'retry_after_attempt':1}
        assert c.post(path+'/confirm',json=retry).status_code==200
        fake.mode='ok'
        result=execute(c,sid,op)
        assert result['status']=='succeeded' and result['attempts']==2 and fake.posts==2
        assert result['payload']==op['payload']
        assert c.post(path+'/confirm',json=retry).json()['status']=='succeeded'
        assert execute(c,sid,op)['attempts']==2 and fake.posts==2


def test_retry_confirmation_cannot_replay_after_another_failure(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    sid,oid=s['session_id'],op['operation_id']
    for attempt in (1,2):
        ops.claim(sid,oid)
        ops.dispatched(sid,oid,{'id':7})
        ops.complete(sid,oid,'failed',error='github_http_403')
        if attempt==1:
            ops.confirm(sid,oid,op['content_hash'],op['confirmation_text'],1)
    with pytest.raises(StateError) as error:
        ops.confirm(sid,oid,op['content_hash'],op['confirmation_text'],1)
    assert error.value.code=='retry_confirmation_mismatch'
    state.edit(sid,s['revision'],'changed','draft')
    with pytest.raises(StateError) as error:
        ops.confirm(sid,oid,op['content_hash'],op['confirmation_text'],2)
    assert error.value.code=='revision_conflict'


def test_explicit_retry_never_rearms_unknown(tmp_path):
    state,ops,s,op=setup_store(tmp_path)
    sid,oid=s['session_id'],op['operation_id']
    ops.claim(sid,oid); ops.dispatched(sid,oid,{'id':7})
    ops.complete(sid,oid,'unknown',error='github_timeout')
    assert ops.confirm(sid,oid,op['content_hash'],op['confirmation_text'],1)['status']=='unknown'
    assert ops.claim(sid,oid)[1] is False
