"""Local readiness is not a claim that remote services or semantic retrieval work."""
import sqlite3
from contextlib import closing


def readiness(settings, knowledge, store):
    try:
        with closing(sqlite3.connect(f"{store.path.resolve().as_uri()}?mode=ro", uri=True, timeout=1)) as db:
            database_ok = db.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 0
    except sqlite3.Error:
        database_ok = False
    checks = {
        "database": database_ok,
        "model_configured": bool(settings.deepseek_api_key.get_secret_value()),
        "knowledge_files": not settings.knowledge_enabled or bool(knowledge and knowledge.ready()),
    }
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks,
            "external_services_checked": False,
            "writes_configured": settings.github_writes_enabled and bool(settings.github_token.get_secret_value())}
