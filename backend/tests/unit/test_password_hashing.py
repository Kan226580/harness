from backend.app.core.security import hash_password, verify_password


def test_same_password_hashes_differ() -> None:
    """相同密码两次哈希不同"""
    password = "demo-passphrase-2026"
    first = hash_password(password)
    second = hash_password(password)
    assert first != second, "两次哈希必须不同，相同说明实现有问题"
    assert first.startswith("$argon2id$"), "哈希格式必须是 Argon2id"


def test_verify_accepts_correct_password() -> None:
    """验证一个明文密码对应正确的哈希"""
    stored = hash_password("demo-passphrase-2026")
    assert verify_password("demo-passphrase-2026", stored) is True


def test_verify_rejects_incorrect_password() -> None:
    """验证一个明文密码无法对应错误的哈希"""
    stored = hash_password("demo-passphrase-2026")
    assert verify_password("incorrect-passphrase", stored) is False


def test_verify_rejects_broken_hash() -> None:
    """验证一个明文密码无法对应损坏的的哈希"""
    assert verify_password("anything", "not-a-real-hash") is False
