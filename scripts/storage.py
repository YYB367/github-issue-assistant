"""List/backup/restore one configured database. Restore requires all owners to stop."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
from app.backups import snapshot, manifests, check_database, database_key, atomic_json, utc_now
from app.config import Settings


def read_operations(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='operations'").fetchone():
            return {}
        return {key:json.loads(raw) for key,raw in db.execute('SELECT id,data FROM operations')}


def restore(settings,backup,allow_new_location=False):
    target=settings.state_db_path.resolve()
    backup=Path(backup).resolve()
    if not backup.is_relative_to(settings.backup_directory.resolve()) or backup==target:
        raise ValueError('select_backup_from_configured_directory')
    data=json.loads(backup.with_suffix('.json').read_text(encoding='utf-8'))
    if data.get('application')!='github-issue-assistant':
        raise ValueError('not_an_application_backup')
    if data.get('database_key')!=database_key(target) and not (allow_new_location and not target.exists()):
        raise ValueError('backup_belongs_to_different_database')
    if allow_new_location and target.exists():
        raise ValueError('new_location_must_not_overwrite_existing_database')
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=data['sha256']:
        raise ValueError('backup_checksum_mismatch')
    if check_database(backup)>2:
        raise ValueError('backup_schema_newer_than_application')
    with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'sessions','tasks','messages'}<=tables:
            raise ValueError('not_an_application_backup')
    target.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(target)+'.owner.lock',timeout=0):
        if target.exists():
            before,after=read_operations(target),read_operations(backup)
            fields=('content_hash','fingerprint','status','attempts','actor','dispatch_started','result')
            for oid,op in before.items():
                if op.get('attempts',0)>0 and (oid not in after or any(op.get(k)!=after[oid].get(k) for k in fields)):
                    raise ValueError('restore_would_lose_github_write_history')
            # Checkpoint before replacing the main file: never combine a backup with stale WAL pages.
            with closing(sqlite3.connect(target,timeout=2)) as db:
                busy,*_=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if busy:
                    raise ValueError('database_still_busy')
            snapshot(target,settings.backup_directory/'protected','pre-restore','before_restore')
        atomic_json(settings.restore_hold_path,{'restored_at':utc_now(),'backup':backup.name,
            'reason':'review GitHub write history before re-enabling writes'})
        temporary=target.with_name(target.name+'.'+uuid4().hex+'.restore-pending')
        try:
            shutil.copyfile(backup,temporary)  # Copy an immutable validated backup, never a running DB.
            check_database(temporary)
            os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)
    return {'status':'restored','database':str(target),'writes_paused_after_restore':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    commands.add_parser('list');commands.add_parser('backup')
    r=commands.add_parser('restore');r.add_argument('file');r.add_argument('--confirm-restore',action='store_true');r.add_argument('--allow-new-location',action='store_true',help='Disaster recovery only: target must not exist')
    a=commands.add_parser('acknowledge-restore');a.add_argument('--reviewed-github-history',action='store_true')
    args=p.parse_args()
    try:
        settings=Settings()
        if args.command=='list':
            result={'database':str(settings.state_db_path.resolve()),'backups':manifests(settings.state_db_path,settings.backup_directory)}
        elif args.command=='backup':
            result=snapshot(settings.state_db_path,settings.backup_directory,'manual','manual_request')
        elif args.command=='restore':
            if not args.confirm_restore:
                p.error('Stop the service, inspect the backup, then pass --confirm-restore')
            result=restore(settings,settings.backup_directory/args.file,args.allow_new_location)
        else:
            if not args.reviewed_github_history:
                p.error('Review remote GitHub results before passing --reviewed-github-history')
            settings.restore_hold_path.unlink(missing_ok=True)
            result={'status':'restore_review_acknowledged','github_writes_still_require_confirmation':True}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and str(error).replace('_','').isalnum() else type(error).__name__
        print(json.dumps({'error':code,'message':'Storage command failed. Check owner lock, backup integrity and write history.'}))
        raise SystemExit(1)

if __name__=='__main__':
    main()
