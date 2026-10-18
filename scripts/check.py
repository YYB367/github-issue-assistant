"""No remote calls. Inspect local configuration, locked versions, storage and KB markers."""
import argparse
import json
import sqlite3
from contextlib import closing
import sys
from importlib.metadata import PackageNotFoundError, version
from packaging.requirements import Requirement
from pathlib import Path
from tempfile import TemporaryFile

from app.config import PROJECT_ROOT, Settings


def inspect(settings):
    dependencies=[]
    for line in (PROJECT_ROOT/'requirements.lock').read_text(encoding='utf-8').splitlines():
        if '==' not in line or line.startswith('#'):
            continue
        requirement=Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        name, expected=requirement.name,next(iter(requirement.specifier)).version
        try:
            installed=version(name)
        except PackageNotFoundError:
            installed=None
        dependencies.append({'package':name,'expected':expected,'installed':installed,'ok':installed==expected})
    checks={'python_3_12':sys.version_info[:2]==(3,12),
            'dependencies':all(d['ok'] for d in dependencies),
            'model_configured':bool(settings.deepseek_api_key.get_secret_value()),
            'knowledge_files':not settings.knowledge_enabled or (
                (settings.knowledge_path/'active.json').is_file() and
                (settings.embedding_model_path/'model-manifest.json').is_file())}
    for name, path in [('state_directory',settings.state_db_path.parent),('log_directory',settings.log_path.parent),('backup_directory',settings.backup_directory)]:
        try:
            path.mkdir(parents=True,exist_ok=True)
            with TemporaryFile(dir=path) as file:
                file.write(b'local startup check')
            checks[name]=True
        except OSError:
            checks[name]=False
    checks['database_integrity']=True
    if settings.state_db_path.exists():
        try:
            with closing(sqlite3.connect(settings.state_db_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                checks['database_integrity']=db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        except sqlite3.Error:
            checks['database_integrity']=False
    return {'status':'ready' if all(checks.values()) else 'not_ready','checks':checks,
            'dependencies':dependencies,'external_services_checked':False,
            'github_writes_enabled':settings.github_writes_enabled,
            'github_token_configured':bool(settings.github_token.get_secret_value()),
            'notes':['Knowledge readiness checks files only; no semantic retrieval or model request is performed.',
                     'The service must acquire the SQLite owner lock; use one process.']}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        report=inspect(Settings())
    except Exception as error:
        report={'status':'not_ready','error':'startup_check_failed','exception_type':type(error).__name__}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['status']=='ready' else 1)

if __name__=='__main__':
    main()
