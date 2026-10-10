import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.core.errors import ApiError


def request_id_of(request: Request) -> str:
    """获取当前请求 id ，没有则临时生成一个"""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def ok(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    """包装成功响应"""
    return {"data": data, "request_id": request_id_of(request)}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    """包装错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "retryable": retryable,
            },
            "request_id": request_id_of(request),
        },
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常处理器，
    作用是把业务异常 ApiError 和未知异常统一转换成规范的 JSON 错误响应，
    避免把堆栈泄露给用户
    """
    if not isinstance(exc, ApiError):
        # 兜底不给用户看堆栈
        return error_response(request, 500, "INTERNAL_ERROR", "服务器内部错误")
    return error_response(
        request,
        exc.status_code,
        exc.code,
        exc.message,
        details=exc.details,
        retryable=exc.retryable,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    请求参数校验异常处理器，
    专门处理 RequestValidationError，
    把 FastAPI/Pydantic 默认的 422 校验错误，
    转换成项目统一的错误响应格式
    """
    fields: list[dict[str, str]] = []
    if isinstance(exc, RequestValidationError):
        fields = [
            {
                "field": ".".join(str(part) for part in err["loc"] if part != "body"),
                "reason": err["msg"],
            }
            for err in exc.errors()
        ]
    return error_response(
        request, 422, "VALIDATION_ERROR", "请求字段不合法", details={"fields": fields}
    )


def install_error_handlers(app: FastAPI) -> None:
    """用于注册异常处理器"""
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
