"""SQLite snapshots and one small background backup worker; no dataset manager."""
import asyncio
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def database_key(path):
    return hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode()).hexdigest()


def atomic_json(path, data):
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.pending')
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def check_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise ValueError('backup_integrity_failed')
        return db.execute('PRAGMA user_version').fetchone()[0]


def _snapshot(source, folder, kind='auto', reason='saved', sequence=0):
    source,folder=Path(source).resolve(),Path(folder)
    if not source.is_file():
        raise ValueError('source_database_missing')
    folder.mkdir(parents=True,exist_ok=True)
    name=f"{kind}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}.sqlite3"
    destination=folder/name
    temporary=destination.with_suffix('.pending')
    started=time.monotonic()
    def progress(status,remaining,total):
        if time.monotonic()-started>15:
            raise TimeoutError('backup_time_budget_exceeded')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=2)) as src:
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst,pages=128,progress=progress,sleep=.05)
        schema=check_database(temporary)
        checksum=hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary,destination)
        manifest={'application':'github-issue-assistant','database_key':database_key(source),
                  'created_at':utc_now(),'kind':kind,'reason':reason,'sequence':sequence,
                  'schema_version':schema,'sha256':checksum,'file':name}
        atomic_json(destination.with_suffix('.json'),manifest)
        return manifest
    except BaseException:
        temporary.unlink(missing_ok=True)
        # A snapshot is advertised only after its sidecar is durably published.
        if not destination.with_suffix('.json').exists():
            destination.unlink(missing_ok=True)
        raise


def snapshot(source,folder,kind='auto',reason='saved',sequence=0):
    from filelock import FileLock
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    with FileLock(str(folder/'.backup.lock'),timeout=5):
        return _snapshot(source,folder,kind,reason,sequence)


def manifests(source, folder, kind=None):
    result=[]
    for file in Path(folder).glob('*.json'):
        try:
            data=json.loads(file.read_text(encoding='utf-8'))
            name=data['file']
            if (data.get('application')=='github-issue-assistant' and data['database_key']==database_key(source)
                    and Path(name).name==name and name.endswith('.sqlite3')
                    and (file.parent/name).is_file() and (kind is None or data['kind']==kind)):
                result.append(data)
        except (ValueError,KeyError,OSError,TypeError):
            continue
    return sorted(result,key=lambda x:x['created_at'],reverse=True)


def prune(source, folder, keep=10):
    folder=Path(folder)
    for data in manifests(source,folder,'auto')[keep:]:
        (folder/data['file']).unlink(missing_ok=True)
        (folder/data['file']).with_suffix('.json').unlink(missing_ok=True)


def protect_upgrade(path, folder):
    path=Path(path)
    if not path.exists():
        return
    schema=check_database(path)
    if schema>2:
        raise ValueError('database_schema_newer_than_application')
    if schema<2:
        snapshot(path,Path(folder)/'protected',kind='upgrade',reason='before_schema_2')


class BackupManager:
    def __init__(self,path,folder,enabled=True,events=None,debounce=.6):
        self.path,self.folder,self.enabled=Path(path),Path(folder),enabled
        self.events,self.debounce=events,debounce
        prior=manifests(path,folder)
        self.latest=prior[0] if prior else None
        self.sequence=self.completed_sequence=0
        self.last_saved_at=None
        self.error=None
        self.running=False
        self.stopping=False
        self.event=asyncio.Event()
        self.worker=None
        self.loop=None

    def start(self):
        self.loop=asyncio.get_running_loop()
        if self.enabled:
            self.worker=asyncio.create_task(self._work())
            self.request(saved=False)  # Baseline snapshot also covers interrupted-task recovery.

    def request(self,saved=True):
        if not self.enabled:
            return
        def enqueue():
            self.sequence+=1
            if saved:
                self.last_saved_at=utc_now()
            self.event.set()
        if self.loop:
            self.loop.call_soon_threadsafe(enqueue)

    async def _work(self):
        while True:
            await self.event.wait()
            self.event.clear()
            if not self.stopping:
                await asyncio.sleep(self.debounce)
                self.event.clear()  # Merge saves made during the debounce window.
            sequence=self.sequence
            self.running=True
            try:
                self.latest=await asyncio.to_thread(snapshot,self.path,self.folder,'auto','saved',sequence)
                await asyncio.to_thread(prune,self.path,self.folder,10)
                self.completed_sequence=sequence
                self.error=None
            except Exception as error:
                self.error='backup_failed'
                if self.events:
                    self.events.emit('backup_failed',error_code=self.error,exception_type=type(error).__name__)
            finally:
                self.running=False
            if self.sequence>sequence:
                self.event.set()
            if self.stopping and not self.event.is_set():
                return

    async def close(self):
        if self.worker:
            self.stopping=True
            self.event.set()
            await self.worker

    def status(self):
        return {'database_path':str(self.path.resolve()),'auto_backup_enabled':self.enabled,
                'last_saved_at':self.last_saved_at,
                'backup_status':'running' if self.running else 'failed' if self.error else
                    'pending' if self.sequence>self.completed_sequence else 'ok' if self.latest else 'not_created',
                'last_backup_at':self.latest['created_at'] if self.latest else None,
                'last_backup_file':self.latest['file'] if self.latest else None,
                'backup_error':self.error,'backup_directory':str(self.folder.resolve()),'retention':10}
