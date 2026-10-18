"""Durable approval and execution state; never derives authorization from model text."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.state import StateError, now


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class OperationStore:
    def __init__(self, store):
        self.store = store

    def _read(self, db, sid, oid):
        self.store._session(db, sid)
        row = db.execute("SELECT data FROM operations WHERE id=? AND session_id=?", (oid,sid)).fetchone()
        if not row:
            raise StateError("operation_not_found",404)
        return json.loads(row[0])

    def _write(self, db, op, status=None, reason=None):
        if status:
            op["status"] = status
        op["updated_at"] = now()
        op["events"].append({"at":op["updated_at"],"status":op["status"],"reason":reason})
        db.execute("UPDATE operations SET data=? WHERE id=?", (json.dumps(op),op["operation_id"]))

    def _current(self, db, op, allow_expired=False):
        session = self.store._session(db, op["session_id"])
        self.store._editable(session, op["source_revision"])
        if session["target"] != {"repository":op["repository"],"issue_number":op["issue_number"]}:
            raise StateError("operation_target_changed")
        if not allow_expired and datetime.fromisoformat(op["expires_at"]) <= datetime.now(timezone.utc):
            raise StateError("confirmation_expired")

    def _unresolved(self, db, op, exclude=None):
        for (raw,) in db.execute("SELECT data FROM operations").fetchall():
            item = json.loads(raw)
            if (item["operation_id"] != exclude and item["repository"].casefold() == op["repository"].casefold()
                    and item["issue_number"] == op["issue_number"]
                    and item["status"] in ("executing","unknown")):
                raise StateError("unresolved_write_on_issue")

    def preview(self, sid, revision, kind, labels):
        with self.store.transaction() as db:
            session = self.store._session(db,sid)
            if session.get("example_id") or session.get("source","configured")!="configured":
                raise StateError("example_is_read_only",403)
            self.store._editable(session,revision)
            base = {"repository":session["target"]["repository"],"issue_number":session["target"]["issue_number"],
                    "kind":kind,"payload":{"body":session["draft"]} if kind == "publish_comment" else {"labels":sorted(labels)}}
            if kind == "publish_comment" and not session["draft"].strip():
                raise StateError("empty_draft",422)
            fingerprint = digest(base)
            self._unresolved(db,base)
            for (raw,) in db.execute("SELECT data FROM operations WHERE fingerprint=?",(fingerprint,)).fetchall():
                old = json.loads(raw)
                if old["status"] == "succeeded":
                    raise StateError("duplicate_completed_operation")
                if (old["session_id"] == sid and old["source_revision"] == revision
                        and old["status"] in ("previewed","confirmed")
                        and datetime.fromisoformat(old["expires_at"]) > datetime.now(timezone.utc)):
                    return old
            if db.execute("SELECT count(*) FROM operations WHERE session_id=?",(sid,)).fetchone()[0] >= 50:
                raise StateError("operation_limit",422)
            self.store.invalidate_operations(db,sid)
            oid = str(uuid4())
            payload = base["payload"].copy()
            if kind == "publish_comment":
                payload["body"] += f"\n\n<!-- issue-assistant-operation:{oid} -->"
            confirmed_content = {**base,"payload":payload}
            op = {**confirmed_content,"operation_id":oid,"session_id":sid,"fingerprint":fingerprint,
                  "content_hash":digest(confirmed_content),"source_revision":revision,
                  "confirmation_text":f"确认 {kind} {base['repository']}#{base['issue_number']}",
                  "target_url":session["issue_url"],"status":"previewed","result":None,"error_code":None,
                  "actor":None,"dispatch_started":False,"attempts":0,"created_at":now(),"updated_at":now(),
                  "expires_at":(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),
                  "events":[{"at":now(),"status":"previewed","reason":None}]}
            db.execute("INSERT INTO operations VALUES(?,?,?,?)",(oid,sid,fingerprint,json.dumps(op)))
            return op

    def get(self,sid,oid):
        with self.store.transaction() as db:
            return self._read(db,sid,oid)

    def list(self,sid):
        with self.store.transaction() as db:
            self.store._session(db,sid)
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM operations WHERE session_id=? ORDER BY rowid",(sid,))]

    def confirm(self,sid,oid,content_hash,text,retry_after_attempt=None):
        with self.store.transaction() as db:
            op = self._read(db,sid,oid)
            if content_hash != op["content_hash"] or text != op["confirmation_text"]:
                raise StateError("confirmation_mismatch")
            if op["status"] in ("succeeded","executing","unknown"):
                return op
            if op["status"] == "failed" and retry_after_attempt is not None:
                if (op["error_code"] not in ("github_http_401","github_http_403","github_http_429")
                        or retry_after_attempt != op["attempts"] or not 1 <= op["attempts"] < 3):
                    raise StateError("retry_confirmation_mismatch")
                self._current(db,op,allow_expired=True)
                self._unresolved(db,op,oid)
                op.update(dispatch_started=False,error_code=None,result=None,
                          expires_at=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat())
                self._write(db,op,"confirmed",f"explicit_retry_after_attempt_{retry_after_attempt}")
                return op
            if op["status"] not in ("previewed","confirmed"):
                raise StateError("operation_not_confirmable")
            self._current(db,op)
            if op["status"] == "previewed":
                self._write(db,op,"confirmed","explicit_user_confirmation")
            return op

    def claim(self,sid,oid,capacity=True):
        with self.store.transaction() as db:
            op = self._read(db,sid,oid)
            if op["status"] in ("succeeded","executing","unknown"):
                return op,False
            if not capacity:
                raise StateError("write_capacity",429)
            if op["status"] != "confirmed":
                raise StateError("confirmation_required")
            self._current(db,op)
            self._unresolved(db,op,oid)
            # A different session may have completed the same preview since it was created.
            for (raw,) in db.execute("SELECT data FROM operations WHERE fingerprint=? AND id<>?",(op["fingerprint"],oid)):
                if json.loads(raw)["status"] == "succeeded":
                    raise StateError("duplicate_completed_operation")
            self._write(db,op,"executing","claimed_before_network")
            return op,True

    def dispatched(self,sid,oid,actor):
        with self.store.transaction() as db:
            op = self._read(db,sid,oid)
            if op["status"] != "executing" or op["dispatch_started"]:
                raise StateError("operation_not_dispatchable")
            op.update(actor=actor,dispatch_started=True,attempts=op["attempts"]+1)
            self._write(db,op,reason="dispatch_intent_persisted")
            return op

    def complete(self,sid,oid,status,result=None,error=None,timings_ms=None):
        with self.store.transaction() as db:
            op = self._read(db,sid,oid)
            if op["status"] not in ("executing","unknown"):
                return op
            op.update(result=result,error_code=error)
            if timings_ms is not None:
                op["timings_ms"] = timings_ms
            self._write(db,op,status,error or "github_result_verified")
            return op

    def cancel(self,sid,oid):
        with self.store.transaction() as db:
            op = self._read(db,sid,oid)
            if op["status"] == "cancelled":
                return op
            if op["status"] not in ("previewed","confirmed"):
                raise StateError("cannot_cancel_dispatched_operation")
            self._write(db,op,"cancelled","user_cancelled_before_execution")
            return op

    def recover(self):
        with self.store.transaction() as db:
            for (raw,) in db.execute("SELECT data FROM operations").fetchall():
                op = json.loads(raw)
                if op["status"] == "executing":
                    status = "unknown" if op["dispatch_started"] else "failed"
                    op["error_code"] = "server_interrupted"
                    self._write(db,op,status,"server_interrupted")
