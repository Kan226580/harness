import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from backend.app.core.errors import ApiError
from backend.app.core.security import (
    derive_csrf_token,
    dummy_verify,
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)
from backend.app.core.settings import settings
from backend.app.models.identity.auth import Organization, User
from backend.app.models.identity.auth import Session as AuthSession

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
LOGIN_FAILED_MESSAGE = "邮箱或密码不正确"
LAST_SEEN_THROTTLE = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedSession:
    """一次登录/轮换产生的会话：原始凭证给浏览器，哈希已经入库"""

    record: AuthSession
    raw_token: str
    csrf_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ----- 会话


def create_session(db: DbSession, user: User) -> IssuedSession:
    """生成随机凭证 -> 只把哈希存库 -> 原始凭证交给调用方写 Cookie"""
    raw_token = new_session_token()
    csrf_token = derive_csrf_token(raw_token)
    record = AuthSession(
        org_id=user.org_id,
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=_now() + timedelta(hours=settings.security.session_ttl_hours),
        last_seen_at=_now(),
    )
    db.add(record)
    db.flush()
    return IssuedSession(record=record, raw_token=raw_token, csrf_token=csrf_token)


def load_session(db: DbSession, raw_token: str) -> AuthSession | None:
    """用原始凭证查会话；过期、已撤销、查不到都返回 None"""
    record = db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
    ).scalar_one_or_none()
    if record is None:
        return None
    now = _now()
    if record.revoked_at is not None or record.expires_at <= now:
        return None
    # last_seen_at 节流更新：每 5 分钟最多写一次，避免每个请求都写库
    if record.last_seen_at is None or now - record.last_seen_at > LAST_SEEN_THROTTLE:
        record.last_seen_at = now
        db.commit()
    return record


def revoke_session(db: DbSession, record: AuthSession) -> None:
    """登出：撤销当前会话"""
    record.revoked_at = _now()
    db.commit()


def change_password(
    db: DbSession,
    user: User,
    current_session: AuthSession,
    *,
    current_password: str,
    new_password: str,
) -> IssuedSession:
    """修改密码：撤销全部旧会话，再发一张新通行证"""
    if current_session.user_id != user.id or current_session.revoked_at is not None:
        raise ApiError(403, "FORBIDDEN", "会话无效。")
    if not verify_password(current_password, user.password_hash):
        raise ApiError(401, "AUTHENTICATION_FAILED", "当前密码不正确")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.lock_version += 1

    now = _now()
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    issued = create_session(db, user)
    db.commit()
    return issued


# ----- 登录


def _record_login_failure(db: DbSession, user: User, now: datetime) -> None:
    """记一次失败；满 5 分钟就锁 15 分钟。这里立刻提交，否则异常路径会丢掉计数"""
    user.failed_login_count += 1
    if user.failed_login_count >= MAX_FAILED_LOGINS:
        user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
    db.commit()


def authenticate(
    db: DbSession,
    *,
    organization_slug: str,
    email: str,
    password: str,
) -> tuple[User, Organization]:
    """校验组织 + 邮箱 + 密码；任何失败都抛统一的 ApiError"""

    # 组织不存在、被停用：统一失败 + 一次等价哈希运算
    organization = db.execute(
        select(Organization).where(Organization.slug == organization_slug.strip().lower())
    ).scalar_one_or_none()
    if organization is None or not organization.is_active:
        dummy_verify(password)
        raise ApiError(401, "AUTHENTICATION_FAILED", LOGIN_FAILED_MESSAGE)

    # 组织/账号不存在、账号被停用：统一失败 + 一次等价哈希运算
    user = db.execute(
        select(User).where(User.org_id == organization.id, User.email == normalize_email(email))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        dummy_verify(password)
        raise ApiError(401, "AUTHENTICATION_FAILED", LOGIN_FAILED_MESSAGE)

    now = _now()

    # 锁定期内：不论密码对错，统一返回锁定提示
    if user.locked_until is not None and user.locked_until > now:
        dummy_verify(password)
        minutes = max(1, math.ceil((user.locked_until - now).total_seconds() / 60))
        raise ApiError(401, "AUTHENTICATION_FAILED", f"账号已临时锁定，请在 {minutes} 分钟后重试")

    # 锁定期已过：清零计数，重新开始
    if user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None

    if not verify_password(password, user.password_hash):
        _record_login_failure(db, user, now)
        raise ApiError(401, "AUTHENTICATION_FAILED", LOGIN_FAILED_MESSAGE)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    return user, organization
