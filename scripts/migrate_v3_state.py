"""Take a consistent V3 snapshot into the V4 database, without stopping the old reader."""
import json
import sqlite3

from app.config import PROJECT_ROOT, Settings


def main():
    source=PROJECT_ROOT/"work"/"sessions.sqlite3"
    destination=Settings().state_db_path
    if source.resolve()==destination.resolve():
        raise RuntimeError("Choose a new V4 STATE_DB_PATH; source and destination must differ")
    if not source.is_file():
        raise RuntimeError("No V3 database found")
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents accidentally replacing a live or already migrated V4 database.
    with destination.open("xb"):
        pass
    with sqlite3.connect(source.as_uri()+"?mode=ro",uri=True) as src,sqlite3.connect(destination) as dst:
        src.backup(dst)
        assert dst.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        report={"source":source.name,"destination":destination.name,"snapshot_only":True,
                "session_count":dst.execute("SELECT count(*) FROM sessions").fetchone()[0],
                "task_count":dst.execute("SELECT count(*) FROM tasks").fetchone()[0]}
    print(json.dumps(report))


if __name__=="__main__":
    main()
