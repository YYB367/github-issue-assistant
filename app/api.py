import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from app.config import Settings
from app.engine import AnalysisRunner
from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.base import StrictModel
from pydantic import Field
from app.errors import find_app_error
from knowledge.models import RetrievalResult
from filelock import FileLock
from app.state import StateStore, StateError
from app.sessions import routes
from app.errors import AppError
from app.operation_store import OperationStore
from app.operations import routes as operation_routes
from app.github_write import WriteError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.local_guard import SameOriginMutationMiddleware
from app.telemetry import EventLog, RequestTelemetryMiddleware, log_analysis
from app.readiness import readiness
from app.backups import BackupManager, protect_upgrade, manifests
from app.instance import identity
from app.version import VERSION
from app.examples import catalog, resolve, runner_for


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    exclude_issue: int = Field(default=0, ge=0)


def http_status(result: AnalyzeResponse) -> int:
    if result.status == "completed":
        return 200
    if result.status == "cancelled":
        return 499
    if result.status == "timed_out":
        return 504
    code = result.error.code if result.error else "internal_error"
    if code in ("invalid_issue_url", "pull_request"):
        return 400
    if code == "repository_not_allowed":
        return 403
    if code == "github_not_found":
        return 404
    if code in ("model_not_configured", "knowledge_not_ready", "embedding_not_ready"):
        return 503
    return 502


def create_app(settings: Settings | None = None, runner_factory=None, writer_factory=None, demo_mode=False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.settings = settings or Settings()
        except Exception:
            raise RuntimeError("invalid_startup_configuration_run_scripts_check") from None
        app.state.knowledge = None
        if app.state.settings.knowledge_enabled:
            from knowledge.retrieval import KnowledgeService
            app.state.knowledge = KnowledgeService(app.state.settings)
        path = app.state.settings.state_db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path) + ".owner.lock")
        lock.acquire(timeout=0)
        app.state.workers = {}
        app.state.write_workers = {}
        try:
            app.state.events = EventLog(app.state.settings.log_path)
            if not path.exists() and manifests(path,app.state.settings.backup_directory):
                raise RuntimeError("database_missing_restore_from_backup_instead_of_creating_empty")
            protect_upgrade(path,app.state.settings.backup_directory)
            app.state.store = StateStore(path)
            app.state.instance = identity(app.state.settings,demo=demo_mode)
            app.state.backups = BackupManager(path,app.state.settings.backup_directory,
                app.state.settings.auto_backup_enabled,app.state.events)
            app.state.backups.start()
            app.state.store.on_commit = app.state.backups.request
            app.state.operations = OperationStore(app.state.store)
            app.state.operations.recover()
            app.state.store.recover()
            app.state.events.emit("startup", version=VERSION)
            yield
        finally:
            workers = list(app.state.workers.values()) + list(app.state.write_workers.values())
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            if getattr(app.state, "backups", None):
                await app.state.backups.close()
            if getattr(app.state, "events", None):
                app.state.events.emit("shutdown", version=VERSION)
                app.state.events.close()
            lock.release()

    app = FastAPI(title="GitHub Issue 分析助手 V5", version=VERSION, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1","localhost","testserver"])
    app.add_middleware(SameOriginMutationMiddleware)
    app.add_middleware(RequestTelemetryMiddleware)
    app.include_router(routes(runner_factory))
    app.include_router(operation_routes(writer_factory))
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    async def interface():
        return FileResponse(static / "index.html", headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "connect-src 'self'; img-src 'self'; object-src 'none'; "
                                       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default validation response can echo invalid input, including pasted secrets.
        return JSONResponse(status_code=422, content={"error": "invalid_request", "request_id": request.state.request_id})

    @app.exception_handler(WriteError)
    async def write_error(request,error):
        return JSONResponse(status_code=502, content={"error":error.code})

    @app.exception_handler(TimeoutError)
    async def bounded_read_timeout(request,error):
        return JSONResponse(status_code=504, content={"error":"read_time_budget_exceeded"})

    @app.exception_handler(StateError)
    async def state_error(request, error):
        return JSONResponse(status_code=error.status, content={"error": error.code})

    @app.exception_handler(AppError)
    async def app_error(request, error):
        status = 403 if error.code == "repository_not_allowed" else 400
        return JSONResponse(status_code=status, content={"error": error.code})

    @app.get("/health")
    async def health():
        config = app.state.settings
        return {
            "status": "ok", "version": VERSION, "mode": "offline_demo" if demo_mode else "live",
            "allowed_repository": config.allowed_repository,
            "model_configured": bool(config.deepseek_api_key.get_secret_value()),
            "external_services_checked": False,
            "knowledge_enabled": config.knowledge_enabled,
            "knowledge_ready": bool(app.state.knowledge and app.state.knowledge.ready()),
            "github_writes_enabled": config.github_writes_enabled,
            "github_token_configured": bool(config.github_token.get_secret_value()),
        }

    @app.get("/examples")
    async def examples():
        return [{k:v for k,v in item.items() if k != "analysis"} for item in catalog()]

    @app.get("/instance", include_in_schema=False)
    async def instance():
        return app.state.instance

    @app.post("/__local/stop", include_in_schema=False)
    async def stop_managed_server(request: Request):
        import hmac
        token=getattr(app.state,"local_control_token",None)
        if not token or not hmac.compare_digest(request.headers.get("X-Local-Control", ""),token):
            raise StateError("local_control_rejected",403)
        if app.state.write_workers:
            raise StateError("wait_for_github_write_before_stop")
        app.state.request_shutdown()
        return {"status":"stopping"}

    @app.get("/storage/status")
    async def storage_status():
        result=app.state.backups.status()
        result["writes_paused_after_restore"]=app.state.settings.restore_hold_path.exists()
        return result

    @app.post("/storage/backup",status_code=202)
    async def request_backup():
        app.state.backups.request(saved=False)
        return {"status":"requested" if app.state.backups.enabled else "disabled"}

    @app.get("/ready")
    async def ready():
        result = readiness(app.state.settings, app.state.knowledge, app.state.store)
        return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)

    @app.post("/knowledge/search", response_model=RetrievalResult)
    async def search(payload: SearchRequest):
        service = app.state.knowledge
        if service is None or not service.ready():
            return JSONResponse(status_code=503, content={"error": "knowledge_not_ready"})
        try:
            result = await asyncio.wait_for(asyncio.to_thread(service.search, payload.query, payload.exclude_issue), timeout=30)
            return result
        except TimeoutError:
            return JSONResponse(status_code=504, content={"error": "knowledge_timeout"})
        except Exception as error:
            safe = find_app_error(error)
            return JSONResponse(status_code=503, content={"error": safe.code if safe else "knowledge_error"})

    @app.post("/analyze", response_model=AnalyzeResponse)
    async def analyze(payload: AnalyzeRequest, request: Request):
        _,use_knowledge,_ = resolve(payload,app.state.settings)
        runner = runner_for(app.state.settings,dict(issue_url=payload.issue_url,example_id=payload.example_id,
                            use_knowledge=use_knowledge),app.state.knowledge,runner_factory)
        worker = asyncio.create_task(runner.run(payload.issue_url))
        try:
            # MCP context managers stay inside worker, so cancellation closes them in their owner task.
            while not worker.done():
                await asyncio.wait({worker}, timeout=0.1)
                if not worker.done() and await request.is_disconnected():
                    worker.cancel()
            result = await worker
        except asyncio.CancelledError:
            worker.cancel()
            await worker
            raise
        log_analysis(app.state.events, result)
        return JSONResponse(status_code=http_status(result), content=result.model_dump(mode="json"))

    return app


app = create_app()
