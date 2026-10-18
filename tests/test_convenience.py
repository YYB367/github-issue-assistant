import asyncio,json,sqlite3,time
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from filelock import FileLock,Timeout

from app.api import create_app
from app.backups import BackupManager,snapshot,manifests,prune,check_database,protect_upgrade
from app.config import Settings
from app.instance import identity,same_instance
from app.schemas import AnalyzeResponse,parse_issue_url
from app.state import StateStore
from scripts.storage import restore
from tests.helpers import config,URL,REPO


def configured(tmp_path,**kwargs):
    return config(state_db_path=tmp_path/'one.db',log_path=tmp_path/'events.jsonl',**kwargs)


def seeded(tmp_path):
    s=configured(tmp_path)
    db=StateStore(s.state_db_path)
    session=db.create(parse_issue_url(URL,REPO),False)
    db.edit(session['session_id'],1,'first draft','draft')
    return s,db,session['session_id']


def test_backup_uses_sqlite_snapshot_with_open_wal_connection(tmp_path):
    s,db,sid=seeded(tmp_path)
    with closing(sqlite3.connect(s.state_db_path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("CREATE TABLE sample(value TEXT)")
        writer.execute("INSERT INTO sample VALUES('committed in WAL')");writer.commit()
        b=snapshot(s.state_db_path,s.backup_directory)
        writer.execute("UPDATE sample SET value='later value'");writer.commit()
        with closing(sqlite3.connect(s.backup_directory/b['file'])) as copy:
            assert copy.execute('SELECT value FROM sample').fetchone()[0]=='committed in WAL'
        assert check_database(s.backup_directory/b['file'])==2


def test_retention_keeps_ten_auto_and_protected_manual(tmp_path):
    s,db,sid=seeded(tmp_path)
    for _ in range(12):snapshot(s.state_db_path,s.backup_directory)
    snapshot(s.state_db_path,s.backup_directory,'manual')
    snapshot(s.state_db_path,s.backup_directory/'protected','upgrade')
    prune(s.state_db_path,s.backup_directory)
    assert len(manifests(s.state_db_path,s.backup_directory,'auto'))==10
    assert len(manifests(s.state_db_path,s.backup_directory,'manual'))==1
    assert len(manifests(s.state_db_path,s.backup_directory/'protected','upgrade'))==1


def test_restore_protects_current_data_and_pauses_writes(tmp_path):
    s,db,sid=seeded(tmp_path)
    b=snapshot(s.state_db_path,s.backup_directory)
    db.edit(sid,2,'second draft','draft')
    result=restore(s,s.backup_directory/b['file'])
    assert result['writes_paused_after_restore'] is True and s.restore_hold_path.exists()
    assert StateStore(s.state_db_path).get(sid)['draft']=='first draft'
    assert len(manifests(s.state_db_path,s.backup_directory/'protected','pre-restore'))==1
    with TestClient(create_app(s.model_copy(update={'github_writes_enabled':True,'github_token':'test-token'}))) as c:
        assert c.get('/storage/status').json()['writes_paused_after_restore'] is True
        op=c.post(f'/sessions/{sid}/operations/preview',json={'expected_revision':2,'kind':'publish_comment'}).json()
        r=c.post(f"/sessions/{sid}/operations/{op['operation_id']}/execute")
        assert r.status_code==403 and r.json()['error']=='restored_state_requires_review'


def test_restore_refuses_running_owner_and_tampered_backup(tmp_path):
    s,db,sid=seeded(tmp_path)
    b=snapshot(s.state_db_path,s.backup_directory)
    path=s.backup_directory/b['file']
    with FileLock(str(s.state_db_path)+'.owner.lock'):
        with pytest.raises(Timeout):restore(s,path)
    path.write_bytes(path.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='checksum'):restore(s,path)
    assert StateStore(s.state_db_path).get(sid)['draft']=='first draft'


def test_restore_refuses_losing_sent_github_operations(tmp_path):
    s,db,sid=seeded(tmp_path)
    b=snapshot(s.state_db_path,s.backup_directory)
    with db.transaction() as sql:
        sql.execute('INSERT INTO operations VALUES(?,?,?,?)',('sent',sid,'fp',json.dumps({'attempts':1,'status':'unknown'})))
    with pytest.raises(ValueError,match='write_history'):restore(s,s.backup_directory/b['file'])
    assert not s.restore_hold_path.exists()


def test_restore_after_database_deletion(tmp_path):
    s,db,sid=seeded(tmp_path)
    b=snapshot(s.state_db_path,s.backup_directory)
    s.state_db_path.unlink()
    restore(s,s.backup_directory/b['file'])
    assert StateStore(s.state_db_path).get(sid)['draft']=='first draft'


async def test_backup_worker_coalesces_and_flushes_on_shutdown(tmp_path):
    s,db,sid=seeded(tmp_path)
    manager=BackupManager(s.state_db_path,s.backup_directory,debounce=.02)
    manager.start();db.on_commit=manager.request
    for n in range(3):db.edit(sid,2+n,'saved '+str(n),'draft')
    for _ in range(100):
        if manager.completed_sequence>=4:break
        await asyncio.sleep(.01)
    assert len(manifests(s.state_db_path,s.backup_directory,'auto'))==1
    assert manager.status()['backup_status']=='ok'
    db.edit(sid,5,'last commit','draft')
    await manager.close()
    latest=manifests(s.state_db_path,s.backup_directory)[0]
    assert StateStore(s.backup_directory/latest['file']).get(sid)['draft']=='last commit'


def test_failed_backup_never_rolls_back_business_commit(tmp_path,monkeypatch):
    def fail(*args,**kwargs):raise OSError('secret upstream message')
    monkeypatch.setattr('app.backups.snapshot',fail)
    s=configured(tmp_path,auto_backup_enabled=True)
    with TestClient(create_app(s)) as c:
        sid=c.post('/sessions',json={'issue_url':URL}).json()['session_id']
        assert c.patch(f'/sessions/{sid}/draft',json={'expected_revision':1,'text':'safely committed'}).status_code==200
        for _ in range(100):
            status=c.get('/storage/status').json()
            if status['backup_status']=='failed':break
            time.sleep(.02)
        assert status['backup_status']=='failed' and status['last_backup_at'] is None
        assert c.get(f'/sessions/{sid}').json()['draft']=='safely committed'
    assert 'secret upstream message' not in s.log_path.read_text(encoding='utf-8')


def test_upgrade_backup_precedes_schema_change(tmp_path):
    s,db,sid=seeded(tmp_path)
    with closing(sqlite3.connect(s.state_db_path)) as sql:sql.execute('PRAGMA user_version=1')
    protect_upgrade(s.state_db_path,s.backup_directory)
    b=manifests(s.state_db_path,s.backup_directory/'protected','upgrade')[0]
    assert check_database(s.backup_directory/'protected'/b['file'])==1
    assert StateStore(s.state_db_path).get(sid)['draft']=='first draft'
    assert check_database(s.state_db_path)==2


def test_launcher_identity_rejects_other_database_and_waits_for_health(tmp_path,monkeypatch):
    from scripts.launcher import probe,wait_and_open
    expected=identity(configured(tmp_path))
    actual=identity(configured(tmp_path).model_copy(update={'state_db_path':tmp_path/'other.db'}))
    def transport(request):return httpx.Response(200,json=actual if request.url.path=='/instance' else {'status':'ok'})
    with httpx.Client(transport=httpx.MockTransport(transport)) as c:
        assert probe('http://127.0.0.1:8008',expected,c) is None
        assert probe('https://evil.test',expected,c) is None
    sequence=iter([None,None,expected]);opened=[]
    monkeypatch.setattr('scripts.launcher.probe',lambda *args:next(sequence))
    monkeypatch.setattr('scripts.launcher.time.sleep',lambda delay:None)
    assert wait_and_open('http://127.0.0.1:8008',expected,opened.append,timeout=1,publish=False)
    assert opened==['http://127.0.0.1:8008']


def test_teaching_cases_need_no_keys_or_network_and_cannot_write(tmp_path):
    def forbidden(*args):raise AssertionError('No model must be constructed')
    with TestClient(create_app(configured(tmp_path),forbidden)) as c:
        items=c.get('/examples').json();teach=next(x for x in items if x['kind']=='teaching_case')
        response=c.post('/sessions',json={'issue_url':teach['issue_url'],'example_id':teach['id']})
        sid=response.json()['session_id']
        task=c.post(f'/sessions/{sid}/tasks',json={'expected_revision':1,'request_key':'case'}).json()
        for _ in range(100):
            task=c.get(f"/sessions/{sid}/tasks/{task['task_id']}").json()
            if task['status']!='running':break
            time.sleep(.01)
        r=task['result']
        assert r['status']=='completed' and r['mode']=='teaching_case'
        assert r['model_calls']==0 and r['tool_trace']==[] and not r['documentation_checked']
        rev=c.get(f'/sessions/{sid}').json()['revision']
        assert c.post(f'/sessions/{sid}/operations/preview',json={'expected_revision':rev,'kind':'publish_comment'}).status_code==403
        assert c.get(f'/sessions/{sid}/available-labels').status_code==403
        assert any(x['session_id']==sid for x in c.get('/sessions').json())


def test_public_example_uses_empty_github_token_and_no_foreign_knowledge(tmp_path):
    captured=[]
    class Runner:
        def __init__(self):self.response=AnalyzeResponse(task_id='set-by-route',status='failed')
        async def run(self,url):return self.response
    def factory(s):captured.append(s);return Runner()
    with TestClient(create_app(configured(tmp_path,github_token='private-write-token',github_writes_enabled=True),factory)) as c:
        item=next(x for x in c.get('/examples').json() if x['kind']=='public_example')
        s=c.post('/sessions',json={'issue_url':item['issue_url'],'example_id':item['id']}).json()
        assert s['source']=='public_example' and s['use_knowledge'] is False
        c.post(f"/sessions/{s['session_id']}/tasks",json={'expected_revision':1,'request_key':'public'})
        for _ in range(100):
            if captured:break
            time.sleep(.01)
        assert captured[0].allowed_repository=='fastapi/fastapi'
        assert captured[0].github_token.get_secret_value()=='' and not captured[0].github_writes_enabled
        assert not captured[0].knowledge_enabled
        assert c.post('/sessions',json={'issue_url':item['issue_url']}).status_code==403
        assert c.post('/sessions',json={'issue_url':URL,'example_id':item['id']}).status_code==400


def test_graceful_stop_requires_private_control_token_and_no_active_write(tmp_path):
    app=create_app(configured(tmp_path))
    stopped=[]
    app.state.local_control_token='private-control-token'
    app.state.request_shutdown=lambda:stopped.append(True)
    with TestClient(app) as c:
        assert c.post('/__local/stop').status_code==403
        assert 'private-control-token' not in c.get('/instance').text
        app.state.write_workers['busy']=object()
        assert c.post('/__local/stop',headers={'X-Local-Control':'private-control-token'}).status_code==409
        app.state.write_workers.clear()
        assert c.post('/__local/stop',headers={'X-Local-Control':'private-control-token'}).status_code==200
        assert stopped==[True]
    assert 'private-control-token' not in (tmp_path/'events.jsonl').read_text(encoding='utf-8')


def test_relative_data_path_is_bound_to_project_not_shell_cwd():
    from app.config import PROJECT_ROOT
    s=config(state_db_path=Path('work/stable.sqlite3'))
    assert s.state_db_path==(PROJECT_ROOT/'work/stable.sqlite3').resolve()


def test_disaster_recovery_at_new_location_requires_explicit_flag_and_missing_target(tmp_path):
    import shutil
    s,db,sid=seeded(tmp_path)
    backup=snapshot(s.state_db_path,s.backup_directory)
    other=configured(tmp_path/'other-location')
    other.backup_directory.mkdir(parents=True)
    source=s.backup_directory/backup['file']
    target=other.backup_directory/backup['file']
    shutil.copyfile(source,target)
    shutil.copyfile(source.with_suffix('.json'),target.with_suffix('.json'))
    with pytest.raises(ValueError,match='different_database'):restore(other,target)
    restore(other,target,allow_new_location=True)
    assert StateStore(other.state_db_path).get(sid)['draft']=='first draft'
    assert other.restore_hold_path.exists()
    with pytest.raises(ValueError):restore(other,target,allow_new_location=True)
