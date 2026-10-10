import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.app.api.errors import error_response
from backend.app.core.settings import settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RequestIdMiddleware(BaseHTTPMiddleware):
    """给每个请求一个 request_id ，成功和错误响应都用它，方便查日志"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """浏览器发写请求会自动带 Origin ,命令行/测试工具不带则放行"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin != settings.security.public_origin:
                return error_response(request, 403, "CSRF_INVALID", "请求来源不被信任")
        return await call_next(request)
