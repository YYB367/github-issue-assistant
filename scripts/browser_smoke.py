"""Optional real-Chrome UI regression against an in-process, offline-only demo server."""
import json
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn

from scripts.demo_v5 import demo_app
from app.version import VERSION
from tests.helpers import URL


def wait(page, expression, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if page.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError("UI condition timed out: "+expression)


def main():
    from playwright.sync_api import sync_playwright
    output=Path('verification');output.mkdir(exist_ok=True)
    report={'mode':'offline_browser_test','github_network_calls':False,'browser':'installed Google Chrome',
            'scenarios':[],'screenshots':[]}
    with TemporaryDirectory(prefix='browser-v5-',dir='work') as folder, sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        failures=[]
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page.on('pageerror',lambda error:failures.append(str(error)))

        def run(mode,port):
            app=demo_app(Path(folder)/mode,mode)
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='warning'))
            thread=threading.Thread(target=server.run,daemon=True);thread.start()
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            assert server.started,'Offline demo failed to start'
            return app,server,thread

        app,server,thread=run('ok',8016)
        try:
            page.goto('http://127.0.0.1:8016/')
            wait(page,f"document.getElementById('health').textContent.includes('{VERSION}')")
            assert not page.locator('#demo').is_hidden()
            page.locator('#issue-url').fill(URL)
            page.locator('#create').click()
            wait(page,"document.getElementById('task-state').textContent==='分析完成'")
            assert page.locator('#trace tr').count()==2
            assert '<script>' in page.locator('#evidence').inner_text()
            assert page.evaluate('window.externalInstruction') is None
            assert page.locator('#evidence script').count()==0
            report['scenarios'].append('submit, two actual loop calls with fake tools, evidence rendered as text')
            page.screenshot(path=str(output/'v5-ui-desktop.png'),full_page=True)
            report['screenshots'].append('v5-ui-desktop.png')
            sid=page.evaluate('S.s.session_id')
            page.locator('#draft').fill('浏览器模拟草稿 <img src=x onerror=alert(1)>')
            page.locator('#save-draft').click()
            wait(page,"document.getElementById('draft-status').textContent==='草稿已保存'")
            page.locator('#preview-comment').click()
            page.locator('#approval').wait_for(state='visible')
            assert page.locator('#confirm-execute').is_disabled() and app.state.fake_github.posts==0
            page.locator('#reviewed').check()
            page.locator('#confirmation-text').fill('错误确认')
            assert page.locator('#confirm-execute').is_disabled()
            exact=page.locator('#expected-text').inner_text()
            page.locator('#confirmation-text').fill(exact)
            assert page.locator('#confirm-execute').is_enabled()
            page.locator('#draft').fill('修改后的模拟草稿')
            assert page.locator('#confirm-execute').is_disabled()
            page.locator('#save-draft').click()
            wait(page,"S.op.status==='invalidated'")
            assert app.state.fake_github.posts==0
            report['scenarios'].append('unconfirmed blocked; wrong text blocked; editing invalidates confirmation')
            page.locator('#preview-comment').click()
            wait(page,"S.op.status==='previewed'")
            oid=page.evaluate('S.op.operation_id')
            page.locator('#reviewed').check();page.locator('#confirmation-text').fill(page.locator('#expected-text').inner_text())
            page.locator('#confirm-execute').click()
            wait(page,"S.op.status==='succeeded'")
            assert app.state.fake_github.posts==1
            repeated=page.request.post(f'http://127.0.0.1:8016/sessions/{sid}/operations/{oid}/execute').json()
            assert repeated['attempts']==1 and app.state.fake_github.posts==1
            report['scenarios'].append('comment confirmed once; repeated execute sends no duplicate')
            page.reload();wait(page,f"S.s?.session_id==='{sid}'")
            assert page.locator('#draft').input_value()=='修改后的模拟草稿'
            assert app.state.fake_github.posts==1
            page.locator('#load-labels').click();page.locator('#label-panel').wait_for(state='visible')
            page.locator('#labels').select_option(['bug'])
            page.locator('#preview-labels').click();wait(page,"S.op?.kind==='add_labels'")
            page.locator('#reviewed').check();page.locator('#confirmation-text').fill(page.locator('#expected-text').inner_text())
            page.locator('#confirm-execute').click();wait(page,"S.op.status==='succeeded'")
            assert app.state.fake_github.labels==['bug'] and app.state.fake_github.posts==2
            report['scenarios'].append('reload restores session without writes; existing label addition')
            page.locator('#supplement').fill('Node 22，补充模拟环境')
            page.locator('#add-supplement').click();wait(page,"S.s.supplements.length===1")
            page.locator('#analyze-again').click();wait(page,"document.getElementById('task-state').textContent==='分析完成' && S.s.task_ids.length===2")
            report['scenarios'].append('supplement saved; new analysis uses separate task')
            page.locator('#issue-url').fill(URL)
            page.locator('#create').click();wait(page,f"S.s?.session_id && S.s.session_id!=='{sid}'")
            page.locator('#cancel-task').wait_for(state='visible');page.locator('#cancel-task').click()
            wait(page,"document.getElementById('task-state').textContent==='已取消'")
            assert page.locator('#supplements li').count()==0
            assert '修改后的模拟草稿' not in page.locator('#draft').input_value()
            report['scenarios'].append('new session isolation; active analysis cancellation')
            page.locator('#draft').fill('取消预览模拟')
            page.locator('#save-draft').click();wait(page,"document.getElementById('draft-status').textContent==='草稿已保存'")
            page.locator('#preview-comment').click();wait(page,"S.op?.status==='previewed'")
            page.locator('#cancel-operation').click();wait(page,"S.op.status==='cancelled'")
            assert app.state.fake_github.posts==2
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(output/'v5-ui-mobile.png'),full_page=True)
            report['screenshots'].append('v5-ui-mobile.png')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            report['scenarios'].append('preview cancellation sends nothing; mobile layout has no page overflow')
            report['successful_demo_github_posts']=app.state.fake_github.posts
        finally:
            server.should_exit=True;thread.join(timeout=10)
        app,server,thread=run('timeout',8017)
        try:
            page.set_viewport_size({'width':1440,'height':1050})
            page.goto('http://127.0.0.1:8017/')
            page.locator('#issue-url').fill(URL);page.locator('#create').click()
            wait(page,"document.getElementById('task-state').textContent==='分析完成'")
            page.locator('#preview-comment').click();wait(page,"S.op?.status==='previewed'")
            page.locator('#reviewed').check();page.locator('#confirmation-text').fill(page.locator('#expected-text').inner_text())
            page.locator('#confirm-execute').click();wait(page,"S.op.status==='unknown'")
            assert page.locator('#confirmation').is_hidden() and app.state.fake_github.posts==1
            page.locator('#reconcile').click();wait(page,"S.op.status==='succeeded'")
            assert app.state.fake_github.posts==1
            report['scenarios'].append('write response lost: unknown forbids resend; read-only reconciliation succeeds')
            report['unknown_demo_github_posts']=app.state.fake_github.posts
        finally:
            server.should_exit=True;thread.join(timeout=10)
        assert not failures,failures
        report['page_errors']=failures
        report['status']='passed'
        browser.close()
    (output/'v5-browser-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    main()
