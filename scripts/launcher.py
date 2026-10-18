"""Double-click launcher: reuse the exact app/database, otherwise start and wait before opening."""
import argparse
import json
import logging
import os
import socket
import secrets
import threading
import time
import webbrowser

import httpx
from filelock import FileLock, Timeout

from app.backups import atomic_json
from app.config import PROJECT_ROOT, Settings
from app.instance import identity, same_instance
from app.version import VERSION

REGISTRY=PROJECT_ROOT/'work'/'instance.json'


def probe(url,expected,client=None):
    """Only local, fixed instance/health paths; never trust a registry-provided arbitrary URL."""
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or parsed.path or parsed.query:
        return None
    own=client is None
    client=client or httpx.Client(trust_env=False,timeout=.7,follow_redirects=False)
    try:
        response=client.get(url+'/instance')
        if response.status_code!=200:
            return None
        actual=response.json()
        if not same_instance(expected,actual):
            return None
        health=client.get(url+'/health')
        if health.status_code!=200 or health.json().get('status')!='ok':
            return None
        return actual
    except (httpx.HTTPError,ValueError):
        return None
    finally:
        if own:client.close()


def registered(expected):
    try:
        data=json.loads(REGISTRY.read_text(encoding='utf-8'))
        actual=probe(data['url'],expected)
        if actual and actual['run_id']==data['run_id']:
            return data['url']
    except (OSError,ValueError,KeyError):
        pass
    return None


def wait_and_open(url,expected,opener=webbrowser.open,timeout=40,publish=True,control_token=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        actual=probe(url,expected)
        if actual:
            if publish:
                atomic_json(REGISTRY,{'url':url,'run_id':actual['run_id'],'project_key':actual['project_key'],
                                      'database_key':actual['database_key'],'pid':os.getpid(),'version':VERSION,'control_token':control_token})
            opener(url)
            return True
        time.sleep(.25)
    return False


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--no-browser',action='store_true',help='Verification only: keep automatic browser opening disabled')
    p.add_argument('--stop',action='store_true',help='Gracefully stop only the matching managed app/database')
    args=p.parse_args()
    settings=Settings();expected=identity(settings)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    if args.stop:
        existing=registered(expected)
        if not existing:
            print('No matching managed instance is running.',flush=True);return
        data=json.loads(REGISTRY.read_text(encoding='utf-8'))
        if not data.get('control_token'):
            raise RuntimeError('This instance was not started with graceful management; stop its terminal first.')
        with httpx.Client(trust_env=False,timeout=5,follow_redirects=False) as client:
            response=client.post(existing+'/__local/stop',headers={'X-Local-Control':data['control_token']})
        if response.status_code!=200:
            raise RuntimeError('Shutdown refused. Wait for active GitHub writes to finish, then try again.')
        print('Graceful shutdown requested; saved state and pending backup will be flushed.',flush=True);return
    settings.state_db_path.parent.mkdir(parents=True,exist_ok=True)
    if not settings.state_db_path.exists() and (list(settings.state_db_path.parent.glob("*.sqlite3")) or list(settings.backup_directory.glob("*.json"))):
        raise RuntimeError("Configured database is missing but existing data/backups were found. Check STATE_DB_PATH or restore; refusing to create an empty database.")
    opener=(lambda url: print('Ready:',url,flush=True)) if args.no_browser else webbrowser.open
    existing=registered(expected)
    if existing:
        print('Already running with the same project and database:',existing,flush=True);opener(existing);return
    gate=FileLock(str(PROJECT_ROOT/'work'/'launcher.lock'))
    try:
        gate.acquire(timeout=0)
    except Timeout:
        for _ in range(120):
            existing=registered(expected)
            if existing:
                print('Already running:',existing,flush=True);opener(existing);return
            time.sleep(.25)
        raise RuntimeError('Another launcher is active but not healthy; do not start a second database') from None
    try:
        # Recheck after acquiring the gate to close the double-click race.
        existing=registered(expected)
        if existing:opener(existing);return
        db_lock=FileLock(str(settings.state_db_path)+'.owner.lock')
        try:
            with db_lock.acquire(timeout=0):pass
        except Timeout:
            raise RuntimeError('The configured database is owned by an old service. Stop that service first; no new database was created.') from None
        url=f'http://127.0.0.1:{settings.launch_port}'
        if probe(url,expected):
            wait_and_open(url,expected,opener,timeout=1);return
        with socket.socket() as test:
            if test.connect_ex(('127.0.0.1',settings.launch_port))==0:
                raise RuntimeError('Port is used by a different/old app. Stop it or change LAUNCH_PORT; keep STATE_DB_PATH unchanged.')
        from scripts.check import inspect
        report=inspect(settings)
        required=('python_3_12','dependencies','state_directory','log_directory','backup_directory','database_integrity')
        if not all(report['checks'][key] for key in required):
            raise RuntimeError('Local startup check failed; run python -m scripts.check')
        import uvicorn
        from app.api import create_app
        print(f'Issue assistant {VERSION}: {url}',flush=True)
        print('Database:',settings.state_db_path.resolve(),flush=True)
        print('Keep this window open. Press Ctrl+C to stop and flush backups.',flush=True)
        app=create_app(settings)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=settings.launch_port,workers=1,
                                           access_log=False,log_level='warning'))
        app.state.local_control_token=secrets.token_urlsafe(32)
        app.state.request_shutdown=lambda:setattr(server,'should_exit',True)
        thread=threading.Thread(target=wait_and_open,args=(url,expected,opener),
                                kwargs={'control_token':app.state.local_control_token},daemon=True)
        thread.start()
        for name in ('httpx','httpx2','openai'):logging.getLogger(name).setLevel(logging.WARNING)
        try:
            server.run()
        finally:
            try:
                if json.loads(REGISTRY.read_text(encoding='utf-8')).get('pid')==os.getpid():REGISTRY.unlink(missing_ok=True)
            except (OSError,ValueError):pass
    finally:
        gate.release()


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Only our fixed RuntimeErrors can be printed; no upstream config validation/input text.
        print(str(error) if isinstance(error,RuntimeError) else 'Launcher failed: '+type(error).__name__,flush=True)
        raise SystemExit(1)
