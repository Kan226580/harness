from fastapi import Response

from backend.app.core.settings import settings

SESSION_COOKIE_NAME = "bid_session"


def _cookie_secure() -> bool:
    """只有生产环境要求 HTTPS ,本地开发用 http 也能登录"""
    return settings.env == "prod"


def _max_age_seconds() -> int:
    return settings.security.session_ttl_hours * 3600


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=_max_age_seconds(),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """登出时删除 cookie ，属性要和设置时一致，浏览器才会认"""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
