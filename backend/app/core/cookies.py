from fastapi import Response

from backend.app.core.settings import settings

SESSION_COOKIE_NAME = "bid_session"


def _cookie_secure() -> bool:
    """只有生产环境要求 HTTPS ,本地开发用 http 也能登录"""
    return settings.env == "prod"


def _max_age_seconds() -> int:
    """cookie 有效期/秒"""
    return settings.security.session_ttl_hours * 3600


def set_session_cookie(response: Response, raw_token: str) -> None:
    """
    往 HTTP 响应里写入一个会话（Session）Cookie

    key: cookie 名字
    value: cookie 值
    max_age: cookie 有效期
    httponly: 禁止 JavaScript 通过 document.cookie 读取
    security: 只在 HTTPS 下发送，生产环境下为 True ，本地开发为 False
    samesite: 跨站请求时的发送策略。 lax 表示普通跳转带 cookie ，跨站不带
    path: cookie 对整个站点的所有路径都生效
    """
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
