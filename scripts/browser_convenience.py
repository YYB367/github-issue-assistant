"""Verify convenience UI against the managed local instance, with every GitHub write blocked."""
import json
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.config import Settings
from scripts.browser_smoke import wait


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-public',action='store_true',help='Reuse an already completed live public analysis; avoid another model request')
    args=parser.parse_args()
    settings=Settings();origin=f'http://127.0.0.1:{settings.launch_port}'
    with httpx.Client(base_url=origin,trust_env=False,timeout=5) as client:
        before=client.get('/instance').json()
        status=client.get('/storage/status').json()
    assert Path(status['database_path'])==settings.state_db_path.resolve()
    report={'mode':'live_convenience_browser','database_path':status['database_path'],
            'github_writes_attempted':False,'scenarios':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/operations/**/confirm',lambda route:route.abort())
        page.route('**/operations/**/execute',lambda route:route.abort())
        page.goto(origin+'/')
        wait(page,"document.getElementById('health').textContent.includes('0.5.1')")
        page.locator('#examples-panel').evaluate('(e)=>e.open=true')
        wait(page,"document.querySelectorAll('#example-picker option').length===10")
        page.locator('#example-picker').select_option('teaching-install')
        page.locator('#open-example').click()
        wait(page,"S.s?.latest_result?.mode==='teaching_case' && !S.s.active_task_id")
        teaching=page.evaluate('S.s')
        assert teaching['latest_result']['model_calls']==0 and teaching['latest_result']['tool_trace']==[]
        assert page.locator('#preview-comment').is_disabled() and page.locator('#load-labels').is_disabled()
        assert not page.locator('#target').get_attribute('href')
        report['scenarios'].append('teaching case works without model/MCP calls and is read-only')
        draft='便捷体验验证：这份草稿应保存在固定数据库及自动备份中。'
        page.locator('#draft').fill(draft);page.locator('#save-draft').click()
        wait(page,"document.getElementById('draft-status').textContent==='草稿已保存'")
        wait(page,"storageState?.backup_status==='ok' && storageState?.last_backup_at")
        sid=teaching['session_id']
        def backup_has_draft():
            current=httpx.get(origin+'/storage/status',trust_env=False).json()
            if not current['last_backup_file']:return False
            with closing(sqlite3.connect((settings.backup_directory/current['last_backup_file']).as_uri()+'?mode=ro',uri=True)) as db:
                row=db.execute('SELECT data FROM sessions WHERE id=?',(sid,)).fetchone()
                if row and json.loads(row[0])['draft']==draft:
                    report['verified_backup_file']=current['last_backup_file'];return True
            return False
        import time
        for _ in range(100):
            if backup_has_draft():break
            time.sleep(.1)
        else:raise AssertionError('Saved draft not found in automatic backup')
        page.reload();wait(page,f"S.s?.session_id==='{sid}'")
        assert page.locator('#draft').input_value()==draft
        report['teaching_session_id']=sid
        report['scenarios'].append('saved draft is in canonical database and verified automatic backup; reload restores it')
        page.locator('#examples-panel').evaluate('(e)=>e.open=true')
        if args.reuse_public:
            candidates=page.request.get(origin+'/sessions?limit=50').json()
            existing=None
            for candidate in candidates:
                saved=page.request.get(origin+'/sessions/'+candidate['session_id']).json()
                if saved.get('example_id')=='fastapi-multipart' and (saved.get('latest_result') or {}).get('status')=='completed':
                    existing=saved['session_id'];break
            assert existing,'No previously completed public analysis to reuse'
            page.locator('#restore-id').fill(existing);page.locator('#restore').click()
        else:
            page.locator('#example-picker').select_option('fastapi-multipart')
            page.locator('#open-example').click()
        report['public_result_reused']=args.reuse_public
        wait(page,"S.s?.example_id==='fastapi-multipart' && S.s.task_ids.length>0 && !S.s.active_task_id",timeout=130)
        result=page.evaluate('S.s.latest_result')
        assert result and result['status']=='completed'
        assert result['target']['repository']=='fastapi/fastapi'
        assert result['model_calls']>0 and len(result['tool_trace'])>=2
        assert not result['documentation_checked'] and result['retrieval'] is None
        assert all(t['arguments']['repository']=='fastapi/fastapi' for t in result['tool_trace'])
        assert page.locator('#preview-comment').is_disabled()
        sid=page.evaluate('S.s.session_id')
        response=page.request.post(origin+f'/sessions/{sid}/operations/preview',data={'expected_revision':page.evaluate('S.s.revision'),'kind':'publish_comment'})
        assert response.status==403
        report['scenarios'].append('real public FastAPI example uses MCP/model with no foreign knowledge; server rejects write preview')
        report['public_session_id']=sid
        report['public_result']=result
        page.screenshot(path='verification/convenience-ui-public.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path='verification/convenience-ui-mobile.png',full_page=True)
        assert not errors,errors
        report['page_errors']=errors
        report['scenarios'].append('mobile layout and visible save/backup status')
        browser.close()
    with httpx.Client(base_url=origin,trust_env=False) as c:
        assert c.get('/instance').json()['run_id']==before['run_id']
        report['final_storage_status']=c.get('/storage/status').json()
    report['status']='passed'
    Path('verification/convenience-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','scenarios':report['scenarios'],
        'public_tool_calls':len(result['tool_trace']),'public_model_calls':result['model_calls'],
        'github_writes_attempted':False,'verified_backup_file':report['verified_backup_file']},ensure_ascii=False))

if __name__=='__main__':main()
