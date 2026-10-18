"""Local instance identity. Port and PID alone are never enough for launcher reuse."""
from uuid import uuid4
from app.backups import database_key
from app.config import PROJECT_ROOT
from app.version import VERSION


def identity(settings,run_id=None,demo=False):
    return {'application':'github-issue-assistant','protocol':1,'version':VERSION,
            'project_key':database_key(PROJECT_ROOT),'database_key':database_key(settings.state_db_path),
            'mode':'offline_demo' if demo else 'live','run_id':run_id or str(uuid4())}


def same_instance(expected,actual):
    return isinstance(actual,dict) and all(actual.get(k)==expected[k] for k in
        ('application','protocol','version','project_key','database_key','mode'))
