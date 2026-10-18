"""V5 boundary checks: readiness, bounded lists, observability, and hostile input."""
import json
import sqlite3
import time

from fastapi.testclient import TestClient

from app.api import create_app
from app.engine import AnalysisRunner
from tests.helpers import URL, config, normal_sequence, SequenceModel, StubTools


def settings(tmp_path, **values):
    return config(state_db_path=tmp_path/'state.db',log_path=tmp_path/'events.jsonl',**values)


def test_liveness_readiness_and_no_remote_claim(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        assert c.get('/health').status_code==200
        r=c.get('/ready')
        assert r.status_code==503
        assert r.json()['checks']=={'database':True,'model_configured':False,'knowledge_files':True}
        assert r.json()['external_services_checked'] is False
    with TestClient(create_app(settings(tmp_path,deepseek_api_key='test-configured'))) as c:
        assert c.get('/ready').status_code==200


def test_session_list_is_bounded_and_excludes_content(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        ids=[]
        for _ in range(3):
            ids.append(c.post('/sessions',json={'issue_url':URL}).json()['session_id'])
        c.patch(f'/sessions/{ids[0]}/draft',json={'expected_revision':1,'text':'private draft'})
        page=c.get('/sessions?limit=2').json()
        assert len(page)==2 and page[0]['session_id']==ids[0]
        assert 'draft' not in page[0] and 'chat_history' not in page[0]
        assert len(c.get('/sessions?limit=2&offset=2').json())==1
        assert c.get('/sessions?limit=51').status_code==422
        assert c.get('/sessions?offset=-1').status_code==422


def test_request_logs_never_echo_body_query_or_invalid_input(tmp_path):
    secret='TEST-SECRET-do-not-log-123'
    with TestClient(create_app(settings(tmp_path,deepseek_api_key=secret,github_token=secret))) as c:
        bad=c.post('/sessions?token='+secret,json={'issue_url':secret,'extra':secret})
        assert bad.status_code==422 and secret not in bad.text
        assert bad.headers['x-request-id'] in bad.text
        c.get('/not-found/'+secret+'?token='+secret)
        c.post('/sessions',json={'issue_url':URL},headers={'Origin':'https://evil.test'})
    raw=(tmp_path/'events.jsonl').read_text(encoding='utf-8')
    assert secret not in raw and 'evil.test' not in raw
    events=[json.loads(x) for x in raw.splitlines()]
    assert any(x.get('route')=='/sessions' and x.get('http_status')==422 for x in events)
    assert any(x.get('route')=='unmatched' and x.get('http_status')==404 for x in events)
    assert all('at' in x and 'event' in x for x in events)


def test_metrics_are_persisted_with_actual_reported_usage(tmp_path):
    app=create_app(settings(tmp_path),lambda s:AnalysisRunner(s,SequenceModel(normal_sequence()),StubTools().connect))
    with TestClient(app) as c:
        sid=c.post('/sessions',json={'issue_url':URL}).json()['session_id']
        t=c.post(f'/sessions/{sid}/tasks',json={'expected_revision':1,'request_key':'metrics'}).json()
        for _ in range(100):
            task=c.get(f"/sessions/{sid}/tasks/{t['task_id']}").json()
            if task['status']!='running':
                break
            time.sleep(.02)
        result=task['result']
        assert result['status']=='completed' and result['usage']['total_tokens']==12
        assert set(result['timings_ms'])=={'mcp_connect','tool_loop','generation','model_total','tool_total'}
        assert all(x>=0 for x in result['timings_ms'].values())
        assert result['timings_ms']['model_total']<=result['elapsed_ms']
        assert c.get(f'/sessions/{sid}').json()['latest_result']['timings_ms']==result['timings_ms']
    logs=[json.loads(x) for x in (tmp_path/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    event=next(x for x in logs if x['event']=='analysis_finished')
    assert event['task_id']==t['task_id'] and event['usage']['total_tokens']==12
    assert 'reply_draft' not in json.dumps(logs)


def test_static_ui_security_headers_and_no_directory_escape(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        page=c.get('/')
        assert page.status_code==200 and 'Issue 工作台' in page.text
        assert "script-src 'self'" in page.headers['content-security-policy']
        assert page.headers['x-content-type-options']=='nosniff'
        assert c.get('/static/app.js').status_code==200
        assert c.get('/static/%2e%2e/.env').status_code==404
        assert c.post('/sessions',json={'issue_url':URL},headers={'Origin':'https://evil.test'}).status_code==403


def test_unexpected_exception_does_not_expose_upstream_text(tmp_path):
    app=create_app(settings(tmp_path))
    @app.get('/test-failure')
    async def failure():
        raise RuntimeError('TEST-upstream-secret')
    with TestClient(app,raise_server_exceptions=False) as c:
        r=c.get('/test-failure')
        assert r.status_code==500 and r.json()['error']=='internal_error'
        assert 'TEST-upstream-secret' not in r.text
    logs=(tmp_path/'events.jsonl').read_text(encoding='utf-8')
    assert 'TEST-upstream-secret' not in logs and 'RuntimeError' in logs


def test_readiness_fails_if_database_disappears(tmp_path):
    # The app holds a file lock, not an indefinitely open SQLite connection.
    with TestClient(create_app(settings(tmp_path,deepseek_api_key='configured'))) as c:
        (tmp_path/'state.db').unlink()
        assert c.get('/ready').status_code==503


def test_startup_check_understands_platform_markers(tmp_path):
    from scripts.check import inspect
    r=inspect(settings(tmp_path,deepseek_api_key='configured'))
    assert r['checks']['dependencies'] is True
    assert all(';' not in d['expected'] for d in r['dependencies'])
    assert r['status']=='ready' and r['external_services_checked'] is False
