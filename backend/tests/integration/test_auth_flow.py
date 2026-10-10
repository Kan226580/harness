from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import ApiError
from backend.app.core.security import hash_password, hash_token
from backend.app.main import app
from backend.app.models import Organization, User
from backend.app.models import Session as AuthSession
from backend.app.modules.identity.dependencies import AuthContext, require_password_changed

DEMO_PASSWORD = "demo-passphrase-2026"
NEW_PASSWORD = "new-passphrase-2026"


def _create_writer(db_session: Session) -> User:
    """创建用户"""
    organization = Organization(slug="auth-flow-org", name="认证演示组织")
    db_session.add(organization)
    db_session.flush()
    user = User(
        org_id=organization.id,
        email="writer@example.invalid",
        display_name="编写者",
        password_hash=hash_password(DEMO_PASSWORD),
        role="writer",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _login(client: TestClient, password: str = DEMO_PASSWORD) -> Any:
    """用户登录"""
    return client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": "auth-flow-org",
            "email": "writer@example.invalid",
            "password": password,
        },
    )


def test_login_sets_cookie_and_hides_secrets(db_session: Session, api_client: TestClient) -> None:
    """检验登录 cookie 以及密码隐藏"""

    # 测试登录后的状态码以及响应体
    _create_writer(db_session)
    response = _login(api_client)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["user"]["email"] == "writer@example.invalid"
    assert len(body["csrf_token"]) == 64

    # 测试响应头
    header = response.headers["set-cookie"]
    assert "bid_session=" in header and "HttpOnly" in header

    # 库里找不到明文密码，也找不到原始会话凭证（只有它的哈希）
    user = db_session.execute(select(User)).scalar_one()
    assert DEMO_PASSWORD not in user.password_hash
    raw_cookie = api_client.cookies["bid_session"]
    stored = db_session.execute(select(AuthSession)).scalars().all()
    assert all(raw_cookie != record.token_hash for record in stored)
    assert any(hash_token(raw_cookie) == record.token_hash for record in stored)

    # me 能拿到和登录一致的 CSRF Token
    me = api_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["csrf_token"] == body["csrf_token"]


def test_unknown_account_and_wrong_password_share_message(
    db_session: Session, api_client: TestClient
) -> None:
    """检验未知用户以及错误密码返回的错误响应"""
    _create_writer(db_session)
    wrong = _login(api_client, "wrong-password")
    unknown = api_client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": "auth-flow-org",
            "email": "nobody@example.invalid",
            "password": "whatever",
        },
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_five_failures_lock_account(db_session: Session, api_client: TestClient) -> None:
    """测试超过 5 次错误登陆后用户锁定情况"""
    _create_writer(db_session)
    for _ in range(5):
        assert _login(api_client, "wrong-password").status_code == 401

    locked_wrong = _login(api_client, "another-wrong-password")
    locked_correct = _login(api_client)  # 密码正确，也进不去

    assert locked_wrong.status_code == locked_correct.status_code == 401
    wrong_error = locked_wrong.json()["error"]
    correct_error = locked_correct.json()["error"]
    assert wrong_error["code"] == correct_error["code"] == "AUTHENTICATION_FAILED"
    assert wrong_error["message"] == correct_error["message"]
    assert "锁定" in wrong_error["message"]

    # 锁定期内不会下发会话
    assert "bid_session" not in api_client.cookies
    assert db_session.execute(select(AuthSession)).scalars().all() == []

    user = db_session.execute(select(User)).scalar_one()
    assert user.locked_until is not None
    assert user.locked_until > datetime.now(UTC)
    assert user.failed_login_count == 5


def test_locked_attempts_do_not_extend_lock(db_session: Session, api_client: TestClient) -> None:
    """测试锁定期内不延长锁定"""
    _create_writer(db_session)
    for _ in range(5):
        _login(api_client, "wrong-password")

    user = db_session.execute(select(User)).scalar_one()
    locked_until_before = user.locked_until
    db_session.refresh(user)

    _login(api_client, "wrong-password")
    _login(api_client)  # 正确密码
    db_session.refresh(user)

    assert user.locked_until == locked_until_before
    assert user.failed_login_count == 5


def test_write_without_csrf_is_rejected(db_session: Session, api_client: TestClient) -> None:
    """测试没有提供 CSFR 导致登出失败"""
    _create_writer(db_session)
    _login(api_client)
    response = api_client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_logout_with_csrf_revokes_session(db_session: Session, api_client: TestClient) -> None:
    """测试提供 CSFR 登出成功，登出后令会话失效"""
    _create_writer(db_session)
    csrf = _login(api_client).json()["data"]["csrf_token"]
    response = api_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204

    again = api_client.get("/api/v1/auth/me")
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "SESSION_EXPIRED"
    assert "会话已过期" in again.json()["error"]["message"]


def test_missing_cookie_returns_session_expired(api_client: TestClient) -> None:
    """检验不存在 cookie 时会话失效"""
    response = api_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_password_change_rotates_and_revokes_other_sessions(
    db_session: Session, api_client: TestClient
) -> None:
    """测试密码轮转以及轮转后失效其他会话"""
    _create_writer(db_session)
    old_csrf = _login(api_client).json()["data"]["csrf_token"]

    with TestClient(app) as other:  # 第二台"设备"
        assert _login(other).status_code == 200

        changed = api_client.post(
            "/api/v1/auth/password",
            headers={"X-CSRF-Token": old_csrf},
            json={"current_password": DEMO_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200
        new_csrf = changed.json()["data"]["csrf_token"]
        assert new_csrf != old_csrf
        assert changed.json()["data"]["user"]["must_change_password"] is False

        # 别人手里那张旧通行证失效了
        assert other.get("/api/v1/auth/me").status_code == 401

        # 当前浏览器拿到新通行证，旧密码不能再登录
        assert api_client.get("/api/v1/auth/me").status_code == 200
        assert _login(api_client, DEMO_PASSWORD).status_code == 401


def test_temporary_password_gate_blocks_business_actions(
    db_session: Session, api_client: TestClient
) -> None:
    """测试 [必须修改密码] 的临时密码门禁"""
    user = _create_writer(db_session)
    user.must_change_password = True
    db_session.flush()

    response = _login(api_client)
    assert response.status_code == 200  # 能登录
    assert api_client.get("/api/v1/auth/me").status_code == 200  # 能看自己

    csrf = response.json()["data"]["csrf_token"]
    assert (
        api_client.post(  # 能登出
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )

    # 直接调用门禁依赖验证逻辑
    record = db_session.execute(select(AuthSession)).scalar_one()
    organization = db_session.get(Organization, user.org_id)
    assert organization is not None
    context = AuthContext(session=record, user=user, organization=organization, raw_token="raw")
    with pytest.raises(ApiError) as exc_info:
        require_password_changed(context)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "PASSWORD_CHANGE_REQUIRED"
