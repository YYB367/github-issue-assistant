import asyncio
from typing import Literal
from uuid import UUID
from time import perf_counter

import httpx
from fastapi import APIRouter, Request
from pydantic import Field, model_validator

from app.base import StrictModel
from app.github_write import GitHubWriter, WriteError
from app.schemas import parse_issue_url
from app.sessions import Revision
from app.state import StateError


class Preview(Revision):
    kind: Literal["publish_comment","add_labels"]
    labels: list[str] = Field(default_factory=list,max_length=5)

    @model_validator(mode="after")
    def valid_labels(self):
        if self.kind == "publish_comment" and self.labels:
            raise ValueError("comment cannot carry labels")
        if self.kind == "add_labels" and (not self.labels or len(set(self.labels)) != len(self.labels)
                or any(not 1<=len(x)<=50 or not x.strip() or any(ord(c)<32 for c in x) for x in self.labels)):
            raise ValueError("provide 1-5 unique existing label names")
        return self


class Confirmation(StrictModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_text: str = Field(min_length=1,max_length=200)
    retry_after_attempt: int | None = Field(default=None,ge=1,le=2)


class Reconcile(StrictModel):
    comment_id: int | None = Field(default=None,gt=0)


def routes(writer_factory=None):
    router = APIRouter(prefix="/sessions/{sid}",tags=["V4 操作预览与确认"])

    def target(state,sid):
        session = state.store.get(sid)
        if session.get("example_id") or session.get("source","configured")!="configured":
            raise StateError("example_is_read_only",403)
        parse_issue_url(session["issue_url"],state.settings.allowed_repository)
        return session

    def writer(settings,client):
        return writer_factory(settings,client) if writer_factory else GitHubWriter(settings,client)

    @router.get("/available-labels")
    async def labels(sid:UUID,request:Request):
        state = request.app.state
        target(state,str(sid))
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(35):
                return await writer(state.settings,client).available_labels()

    @router.post("/operations/preview",status_code=201)
    async def preview(sid:UUID,payload:Preview,request:Request):
        state = request.app.state
        target(state,str(sid))
        return state.operations.preview(str(sid),payload.expected_revision,payload.kind,payload.labels)

    @router.get("/operations")
    async def listing(sid:UUID,request:Request):
        return request.app.state.operations.list(str(sid))

    @router.get("/operations/{oid}")
    async def get(sid:UUID,oid:UUID,request:Request):
        return request.app.state.operations.get(str(sid),str(oid))

    @router.post("/operations/{oid}/confirm")
    async def confirm(sid:UUID,oid:UUID,payload:Confirmation,request:Request):
        state = request.app.state
        target(state,str(sid))
        return state.operations.confirm(str(sid),str(oid),payload.content_hash,payload.confirmation_text,payload.retry_after_attempt)

    @router.post("/operations/{oid}/cancel")
    async def cancel(sid:UUID,oid:UUID,request:Request):
        return request.app.state.operations.cancel(str(sid),str(oid))

    async def execute_operation(state,sid,oid):
        dispatched = False
        started, phase_started, timings = perf_counter(), perf_counter(), {}

        def finish(status, result=None, error=None):
            timings["total"] = round((perf_counter()-started)*1000, 2)
            phase = "write" if dispatched else "preflight"
            timings[phase] = round((perf_counter()-phase_started)*1000, 2)
            op = state.operations.complete(sid,oid,status,result,error,timings)
            state.events.emit("operation_finished", session_id=sid, operation_id=oid, status=op["status"],
                              error_code=op["error_code"], attempts=op["attempts"], timings_ms=timings)

        try:
            op = state.operations.get(sid,oid)
            async with httpx.AsyncClient() as client:
                tool = writer(state.settings,client)
                async with asyncio.timeout(60):
                    actor = await tool.preflight(op)
                    timings["preflight"] = round((perf_counter()-phase_started)*1000, 2)
                    op = state.operations.dispatched(sid,oid,actor)
                    dispatched = True
                    phase_started = perf_counter()
                    result = await tool.send(op)
                    finish("succeeded",result)
        except WriteError as e:
            finish("unknown" if e.uncertain else "failed",error=e.code)
        except (asyncio.CancelledError,TimeoutError):
            finish("unknown" if dispatched else "failed",error="execution_interrupted")
        except Exception:
            finish("unknown" if dispatched else "failed",error="execution_error")
        finally:
            state.write_workers.pop(oid,None)

    @router.post("/operations/{oid}/execute",status_code=202)
    async def execute(sid:UUID,oid:UUID,request:Request):
        state = request.app.state
        target(state,str(sid))
        if state.settings.restore_hold_path.exists():
            raise StateError("restored_state_requires_review",403)
        if not state.settings.github_writes_enabled:
            raise StateError("writes_disabled",403)
        if not state.settings.github_token.get_secret_value():
            raise StateError("github_token_missing",503)
        op,fresh = state.operations.claim(str(sid),str(oid),capacity=len(state.write_workers)<2)
        if fresh:
            state.write_workers[str(oid)] = asyncio.create_task(execute_operation(state,str(sid),str(oid)))
        return op

    @router.post("/operations/{oid}/reconcile")
    async def reconcile(sid:UUID,oid:UUID,payload:Reconcile,request:Request):
        state = request.app.state
        target(state,str(sid))
        op = state.operations.get(str(sid),str(oid))
        if op["status"] == "succeeded":
            return op
        if op["status"] != "unknown":
            raise StateError("reconcile_requires_unknown")
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(45):
                result = await writer(state.settings,client).reconcile(op,payload.comment_id)
        if result is not None:
            return state.operations.complete(str(sid),str(oid),"succeeded",result)
        return op  # missing match is NOT permission to retry

    return router
