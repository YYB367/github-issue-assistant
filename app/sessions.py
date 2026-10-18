"""V3 HTTP workflow; one local process owns tasks for one SQLite file."""
import asyncio
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, Request, Query
from pydantic import Field, field_validator

from app.base import StrictModel
from app.engine import AnalysisRunner
from app.schemas import AnalyzeRequest, parse_issue_url
from app.state import StateError
from app.telemetry import log_analysis
from app.examples import resolve, runner_for, catalog


class Revision(StrictModel):
    expected_revision: int = Field(ge=1)


class TextChange(Revision):
    text: str = Field(min_length=1, max_length=3000)

    @field_validator("text")
    @classmethod
    def nonempty(cls, text):
        if not text.strip():
            raise ValueError("text must not be blank")
        return text


class StartTask(Revision):
    request_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


def routes(runner_factory=None):
    router = APIRouter(prefix="/sessions", tags=["V3 会话与任务"])

    @router.post("", status_code=201)
    async def create(payload: AnalyzeRequest, request: Request):
        settings = request.app.state.settings
        target, use_knowledge, source = resolve(payload,settings)
        return request.app.state.store.create(target,use_knowledge,payload.example_id,source)

    @router.get("/{sid}")
    async def get(sid: UUID, request: Request):
        return request.app.state.store.get(str(sid))

    @router.get("")
    async def listing(request: Request, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        state = request.app.state
        return state.store.listing(state.settings.allowed_repository, limit, offset,tuple(x["repository"] for x in catalog()))

    @router.post("/{sid}/supplements")
    async def supplement(sid: UUID, payload: TextChange, request: Request):
        return request.app.state.store.edit(str(sid), payload.expected_revision, payload.text, "supplement")

    @router.patch("/{sid}/draft")
    async def draft(sid: UUID, payload: TextChange, request: Request):
        return request.app.state.store.edit(str(sid), payload.expected_revision, payload.text, "draft")

    async def execute(state, task):
        sid, tid = task["session_id"], task["task_id"]
        try:
            runner = runner_for(state.settings,task,state.knowledge,runner_factory)
            runner.response.task_id = tid
            runner.continuation = task["context"]
            result = await runner.run(task["issue_url"])
            state.store.finish(sid, tid, result.model_dump(mode="json"))
            log_analysis(state.events, result, sid)
        except asyncio.CancelledError:
            state.store.interrupt(sid, tid)
        except Exception:
            state.store.interrupt(sid, tid, "task_execution_error")
            state.events.emit("analysis_worker_failed", session_id=sid, task_id=tid, error_code="task_execution_error")
        finally:
            state.workers.pop(tid, None)

    @router.post("/{sid}/tasks", status_code=202)
    async def start(sid: UUID, payload: StartTask, request: Request):
        state = request.app.state
        # Recheck persisted targets if the allowlist has changed since session creation.
        session = state.store.get(str(sid))
        from app.schemas import AnalyzeRequest
        resolve(AnalyzeRequest(issue_url=session["issue_url"],example_id=session.get("example_id"),
                               use_knowledge=session["use_knowledge"]),state.settings)
        task, fresh = state.store.start(str(sid), payload.expected_revision, payload.request_key,
                                       capacity=len(state.workers) < 2)
        if fresh:
            state.workers[task["task_id"]] = asyncio.create_task(execute(state, task))
        return task

    @router.get("/{sid}/tasks/{tid}")
    async def task(sid: UUID, tid: UUID, request: Request):
        return request.app.state.store.task(str(sid), str(tid))

    @router.post("/{sid}/tasks/{tid}/cancel")
    async def cancel(sid: UUID, tid: UUID, request: Request):
        state = request.app.state
        result = state.store.interrupt(str(sid), str(tid))
        worker = state.workers.get(str(tid))
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            state.workers.pop(str(tid), None)
        return result

    return router
