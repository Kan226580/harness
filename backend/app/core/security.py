import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.app.core.settings import settings

_password_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = _password_hasher.hash("dummy-password-for-timing-only")

SESSION_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """生成 argon2id 哈希字符串"""
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """校验密码。哈希损坏、格式不对等异常一律 不通过"""
    try:
        return _password_hasher.verify(hashed_password, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """账号不存在时调用，消耗与真实校验相近的计算时间"""
    verify_password(password, _DUMMY_PASSWORD_HASH)


def new_session_token() -> str:
    """生成原始会话凭证，只发给浏览器，永远不写数据库"""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """sha256 十六进制字符串，恰好 64 个字符，正好填满 char(64) 列"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def derive_csrf_token(session_token: str) -> str:
    """用签名密钥和原始会话凭证派生 CSRF Token ,同样的输入永远得到同样的结果"""
    key = settings.security.csrf_signing_key.get_secret_value().encode("utf-8")
    payload = session_token.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_csrf_token(session_token: str, provided: str | None, stored_hash: str) -> bool:
    """恒定时间比较：请求头里的值要能重算出来，还要和库里的哈希一致"""
    if not provided:
        return False
    expected = derive_csrf_token(session_token)
    if not hmac.compare_digest(provided, expected):
        return False
    return hmac.compare_digest(hash_token(provided), stored_hash)
