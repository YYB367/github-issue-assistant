"""Small, allowlisted JSON event log. Never accepts request bodies or exception text."""
import json
import logging
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from time import perf_counter
from uuid import uuid4


class EventLog:
    FIELDS = {"request_id", "session_id", "task_id", "operation_id", "status", "error_code",
              "exception_type", "method", "route", "http_status", "elapsed_ms", "model_calls",
              "tool_calls", "attempts", "timings_ms", "usage", "version"}

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        # Separate from root/SDK loggers; tests and multiple app objects don't add shared handlers.
        self.logger = logging.Logger("issue-assistant-events", level=logging.INFO)
        self.logger.addHandler(self.handler)

    def emit(self, event, **values):
        record = {"at": datetime.now(timezone.utc).isoformat(), "event": event}
        for key in self.FIELDS & values.keys():
            value = values[key]
            if key in ("usage", "timings_ms"):
                value = {k: v for k, v in value.items()
                         if re.fullmatch(r"[a-z_]{1,40}", k) and type(v) in (int, float)}
            elif isinstance(value, str):
                value = value[:150]
            record[key] = value
        self.logger.info(json.dumps(record, ensure_ascii=False))

    def close(self):
        self.handler.close()


class RequestTelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started, request_id, status = perf_counter(), str(uuid4()), 500
        response_started = False
        scope.setdefault("state", {})["request_id"] = request_id

        async def observed_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id.encode()), (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff")]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as error:
            # Handle before ServerErrorMiddleware: Uvicorn must not log raw upstream exception text.
            app = scope.get("app")
            log = getattr(getattr(app, "state", None), "events", None)
            if log:
                log.emit("request_failed", request_id=request_id,
                         exception_type=type(error).__name__, error_code="internal_error")
            if not response_started:
                from starlette.responses import JSONResponse
                await JSONResponse(status_code=500, content={"error":"internal_error", "request_id":request_id})(
                    scope, receive, observed_send)
            else:
                await send({"type":"http.response.body", "body":b"", "more_body":False})
        finally:
            app = scope.get("app")
            log = getattr(getattr(app, "state", None), "events", None)
            if log:
                # A route template contains no user-supplied path/query/ID. Unknown paths use a constant.
                route = getattr(scope.get("route"), "path", "unmatched")
                log.emit("http_request", request_id=request_id, method=scope["method"], route=route,
                         http_status=status, elapsed_ms=round((perf_counter()-started)*1000, 2))


def log_analysis(log, result, session_id=None):
    log.emit("analysis_finished", session_id=session_id, task_id=result.task_id, status=result.status,
             error_code=result.error.code if result.error else None, elapsed_ms=result.elapsed_ms,
             model_calls=result.model_calls, tool_calls=len(result.tool_trace),
             timings_ms=result.timings_ms, usage=result.usage)
