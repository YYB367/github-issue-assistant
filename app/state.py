"""Small transactional business store. No model messages or credentials are persisted."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class StateError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


class StateStore:
    def __init__(self, path):
        self.path = path
        self.on_commit = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    signature TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(session_id, request_key));
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS operation_session ON operations(session_id);
                CREATE INDEX IF NOT EXISTS operation_fingerprint ON operations(fingerprint);
                PRAGMA user_version=2;
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
            if db.total_changes and self.on_commit:
                self.on_commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _session(self, db, sid):
        row = db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise StateError("session_not_found", 404)
        return json.loads(row[0])

    def _save(self, db, session):
        session["revision"] += 1
        session["updated_at"] = now()
        db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session), session["session_id"]))

    def _message(self, db, sid, role, content):
        db.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                   (sid, role, content, now()))
        db.execute("DELETE FROM messages WHERE session_id=? AND id NOT IN "
                   "(SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 50)", (sid, sid))

    def create(self, target, use_knowledge, example_id=None, source="configured"):
        session = dict(session_id=str(uuid4()), target=target.model_dump(), issue_url=target.url,
                       use_knowledge=use_knowledge, example_id=example_id, source=source, revision=1, supplements=[], draft="",
                       draft_source="none", latest_result=None, active_task_id=None,
                       pending_operations=[], operation_status="idle",
                       created_at=now(), updated_at=now())
        with self.transaction() as db:
            db.execute("INSERT INTO sessions VALUES(?,?)", (session["session_id"], json.dumps(session)))
        return session

    def get(self, sid):
        with self.transaction() as db:
            session = self._session(db, sid)
            session["chat_history"] = [dict(role=r, content=c, created_at=t) for r,c,t in db.execute(
                "SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY id", (sid,))]
            session["task_ids"] = [r[0] for r in db.execute(
                "SELECT id FROM tasks WHERE session_id=? ORDER BY rowid", (sid,))]
            operations = [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM operations WHERE session_id=? ORDER BY rowid", (sid,))]
            session["pending_operations"] = [o["operation_id"] for o in operations
                if o["status"] in ("previewed", "confirmed", "executing", "unknown")]
            session["operation_status"] = operations[-1]["status"] if operations else "idle"
            return session

    def listing(self, repository, limit=20, offset=0, extra_repositories=()):
        with self.transaction() as db:
            # Bound returned state; do not include drafts, chat messages or model context in the list.
            repositories=tuple(dict.fromkeys([repository.casefold()]+[x.casefold() for x in extra_repositories]))
            marks=','.join('?' for _ in repositories)
            rows = db.execute("SELECT data FROM sessions WHERE lower(json_extract(data, '$.target.repository')) IN ("+marks+") "
                              "ORDER BY json_extract(data, '$.updated_at') DESC, rowid DESC LIMIT ? OFFSET ?",
                              (*repositories, limit, offset)).fetchall()
        fields = ("session_id", "target", "updated_at", "revision", "active_task_id")
        return [{k: s[k] for k in fields} for s in map(lambda r: json.loads(r[0]), rows)]

    def _editable(self, session, revision):
        if session["revision"] != revision:
            raise StateError("revision_conflict")
        if session["active_task_id"]:
            raise StateError("task_running")

    def invalidate_operations(self, db, sid):
        for (raw,) in db.execute("SELECT data FROM operations WHERE session_id=?", (sid,)).fetchall():
            op = json.loads(raw)
            if op["status"] == "executing":
                raise StateError("operation_executing")
            if op["status"] in ("previewed", "confirmed"):
                op["status"] = "invalidated"
                op["events"].append({"at":now(), "status":"invalidated", "reason":"session_changed"})
                db.execute("UPDATE operations SET data=? WHERE id=?", (json.dumps(op), op["operation_id"]))

    def edit(self, sid, revision, text, kind):
        with self.transaction() as db:
            session = self._session(db, sid)
            self._editable(session, revision)
            self.invalidate_operations(db, sid)
            if kind == "supplement":
                values = session["supplements"] + [text]
                if len(values) > 12 or sum(map(len, values)) > 6000:
                    raise StateError("supplement_budget", 422)
                session["supplements"] = values
            else:
                session["draft"] = text
                session["draft_source"] = "user"
            session["pending_operations"] = []
            self._message(db, sid, "user", text)
            self._save(db, session)
        return self.get(sid)

    def start(self, sid, revision, request_key, capacity=True):
        signature = hashlib.sha256(str(revision).encode()).hexdigest()
        with self.transaction() as db:
            session = self._session(db, sid)
            old = db.execute("SELECT signature,data FROM tasks WHERE session_id=? AND request_key=?",
                             (sid, request_key)).fetchone()
            if old:
                if old[0] != signature:
                    raise StateError("idempotency_conflict")
                return json.loads(old[1]), False
            if not capacity:
                raise StateError("server_busy", 429)
            self._editable(session, revision)
            self.invalidate_operations(db, sid)
            if db.execute("SELECT count(*) FROM tasks WHERE session_id=?", (sid,)).fetchone()[0] >= 20:
                raise StateError("session_task_limit", 422)
            previous = (session["latest_result"] or {}).get("analysis") or {}
            context = dict(supplements=session["supplements"], previous_summary=previous.get("summary", "")[:1000],
                           current_draft=session["draft"])
            # At most 6000 supplement chars + 1000 summary + 3000 draft; UTF-8 checked too.
            if len(json.dumps(context, ensure_ascii=False).encode()) > 24000:
                raise StateError("continuation_context_limit", 422)
            task = dict(task_id=str(uuid4()), session_id=sid, status="running", result=None,
                        context=context, issue_url=session["issue_url"], use_knowledge=session["use_knowledge"],
                        example_id=session.get("example_id"), source=session.get("source","configured"),
                        created_at=now(), finished_at=None)
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)", (task["task_id"], sid, request_key, signature, json.dumps(task)))
            session["active_task_id"] = task["task_id"]
            self._save(db, session)
        return task, True

    def task(self, sid, tid):
        with self.transaction() as db:
            self._session(db, sid)
            row = db.execute("SELECT data FROM tasks WHERE id=? AND session_id=?", (tid,sid)).fetchone()
            if not row:
                raise StateError("task_not_found", 404)
            return json.loads(row[0])

    def finish(self, sid, tid, result):
        with self.transaction() as db:
            session = self._session(db, sid)
            row = db.execute("SELECT data FROM tasks WHERE id=? AND session_id=?", (tid,sid)).fetchone()
            if not row:
                raise StateError("task_not_found", 404)
            task = json.loads(row[0])
            if task["status"] != "running":
                return  # cancellation/recovery wins over a late result
            task.update(status=result["status"], result=result, finished_at=now())
            db.execute("UPDATE tasks SET data=? WHERE id=?", (json.dumps(task), tid))
            session["active_task_id"] = None
            if result["status"] == "completed":
                session["latest_result"] = result
                session["draft"] = result["analysis"]["reply_draft"]
                session["draft_source"] = "model"
                self._message(db, sid, "assistant", session["draft"])
            self._save(db, session)

    def interrupt(self, sid, tid, code="task_cancelled"):
        task = self.task(sid, tid)
        self.finish(sid, tid, dict(task_id=tid, status="cancelled" if code == "task_cancelled" else "failed",
                                 analysis=None, error=dict(code=code, message="任务已停止，请显式创建新任务重试。")))
        return self.task(sid, tid)

    def recover(self):
        with self.transaction() as db:
            tasks = [json.loads(r[0]) for r in db.execute("SELECT data FROM tasks")]
        for task in tasks:
            if task["status"] == "running":
                self.interrupt(task["session_id"], task["task_id"], "server_interrupted")
