"""Read-only live UI acceptance. No confirmation or GitHub write endpoint is called."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from scripts.browser_smoke import wait
from app.version import VERSION
from tests.helpers import URL


def main():
    from playwright.sync_api import sync_playwright
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',default='http://127.0.0.1:8005')
    args=p.parse_args();parts=urlsplit(args.base_url)
    if parts.scheme!='http' or parts.hostname not in ('127.0.0.1','localhost') or parts.path or parts.query or parts.username or parts.password:
        p.error('Use a loopback origin without path, credentials or query')
    origin=args.base_url
    with httpx.Client(base_url=origin,trust_env=False,timeout=10) as c:
        health=c.get('/health').json();ready=c.get('/ready').json()
    assert health['version']==VERSION and health['mode']=='live' and ready['status']=='ready'
    report={'mode':'live_browser_read_only','health':health,'readiness':ready,'github_writes_attempted':False}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        page_errors=[];page.on('pageerror',lambda error:page_errors.append(str(error)))
        # An accidental write action would be blocked even if this script were modified incorrectly.
        page.route('**/operations/**/confirm',lambda route:route.abort())
        page.route('**/operations/**/execute',lambda route:route.abort())
        page.goto(origin+'/');wait(page,f"document.getElementById('health').textContent.includes('{VERSION}')")
        page.locator('#issue-url').fill(URL);page.locator('#create').click()
        wait(page,"S.s?.task_ids.length>0 && !S.s.active_task_id",timeout=120)
        sid=page.evaluate('S.s.session_id')
        result=page.evaluate('S.s.latest_result')
        if not result:
            task=page.request.get(origin+f'/sessions/{sid}/tasks/'+page.evaluate('S.s.task_ids.at(-1)')).json()
            result=task['result']
        report.update(session_id=sid,result=result,page_errors=page_errors,browser_version=browser.version)
        assert result['status']=='completed',result.get('error')
        assert result['mode']=='live' and {x['name'] for x in result['tool_trace']}=={'get_issue','list_issue_comments'}
        assert result['usage'] and result['timings_ms'] and result['retrieval'] is not None
        assert not page_errors,page_errors
        page.screenshot(path='verification/v5-ui-live.png',full_page=True)
        browser.close()
    Path('verification/v5-live-read-only.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'tool_calls':len(result['tool_trace']),
        'usage':result['usage'],'evidence_count':len(result['retrieval']['evidence']),
        'session_id':sid,'github_writes_attempted':False},ensure_ascii=False))

if __name__=='__main__':
    main()
