from fastapi import Response

from backend.app.core.cookies import set_session_cookie
from backend.app.core.security import derive_csrf_token, hash_token, verify_csrf_token


def test_csrf_is_derived_repeatably() -> None:
    """检验同一个 session_token 使用 csrf 能够计算出相同的 token"""
    raw = "raw-session-token-for-test"
    assert derive_csrf_token(raw) == derive_csrf_token(raw), "同样的输入必须得到同样的 Token"
    assert len(derive_csrf_token(raw)) == 64


def test_csrf_changes_with_session_token() -> None:
    """检验不同 session_token 使用 csrf 能够计算出的 token 不同"""
    assert derive_csrf_token("token-a") != derive_csrf_token("token-b")


def test_verify_csrf_checks_header_and_stored_hash() -> None:
    """检验 session_token 与 csrf 计算出的相同，另外与数据库里的哈希对比一致"""
    raw = "raw-session-token-for-test"
    token = derive_csrf_token(raw)
    assert verify_csrf_token(raw, token, hash_token(token)) is True
    assert verify_csrf_token(raw, token + "x", hash_token(token)) is False
    assert verify_csrf_token(raw, None, hash_token(token)) is False


def test_cookie_is_httponly_lax_and_not_secure_in_dev() -> None:
    """检测 set_session_cookie 在 开发/测试 环境下生成的 set-cookie 头是否符合预期"""
    response = Response()
    set_session_cookie(response, "raw-token")
    header = response.headers["set-cookie"]
    assert "bid_session=raw-token" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header  # 测试/开发环境不是 prod
    assert "Max-Age=43200" in header  # 12 小时
