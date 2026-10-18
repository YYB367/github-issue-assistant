"""Check browser mutation origin without consuming the ASGI disconnect channel."""
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class SameOriginMutationMiddleware:
    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        if scope["type"]=="http" and scope["method"] not in ("GET","HEAD","OPTIONS"):
            headers={k.lower():v for k,v in scope.get("headers",[])}
            origin=headers.get(b"origin")
            if origin:
                try:
                    parts=urlsplit(origin.decode("latin1"))
                    valid=(parts.scheme==scope.get("scheme","http")
                           and parts.netloc==headers.get(b"host",b"").decode("latin1"))
                except ValueError:
                    valid=False
                if not valid:
                    response=JSONResponse(status_code=403,content={"error":"cross_origin_mutation_rejected"})
                    await response(scope,receive,send)
                    return
        await self.app(scope,receive,send)
