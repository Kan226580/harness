import os
import re
import subprocess
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.core.settings import BASE_DIR, settings
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models import Organization, User

# 测试库名：默认 harness_test，可用 HARNESS_TEST_DB_NAME 覆盖
TEST_DB_NAME_ENV = "HARNESS_TEST_DB_NAME"
DEFAULT_TEST_DB_NAME = "harness_test"

# 用来检查 / 创建测试库的维护库；测试数据不会写在这里
MAINTENANCE_DB_NAME = "postgres"

# 只接受「小写字母开头，只含小写字母、数字、下划线」的库名，避免拼接 DDL 时带入奇怪字符
SAFE_DB_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _test_db_name() -> str:
    """解析测试库名，并保证它绝对不会落在开发库上。"""
    name = os.environ.get(TEST_DB_NAME_ENV, "").strip() or DEFAULT_TEST_DB_NAME
    if not SAFE_DB_NAME_PATTERN.fullmatch(name):
        raise RuntimeError(
            f"测试库名 {name!r} 不合法：只允许小写字母、数字和下划线，且以小写字母开头。"
        )
    if not name.endswith("_test"):
        raise RuntimeError(f"测试库名 {name!r} 必须以 _test 结尾，防止误用开发库。")
    if name == settings.db.name:
        raise RuntimeError(
            f"测试库名 {name!r} 与开发库（DB__NAME={settings.db.name}）同名，"
            f"拒绝执行集成测试：请用 {TEST_DB_NAME_ENV} 指定一个独立的测试库。"
        )
    return name


def _test_db_url() -> URL:
    """沿用开发库的连接参数（主机、端口、账号），但把库名换成测试库。"""
    url = make_url(settings.db.url)
    driver = url.drivername
    if "async" in driver:
        # 配置里的默认驱动可能是 asyncpg 这类异步驱动，测试用同步驱动连（依赖里已包含 psycopg2-binary）
        driver = "postgresql+psycopg2"
    return url.set(drivername=driver, database=_test_db_name())


def _skip_if_database_unavailable(test_url: URL) -> None:
    """数据库连不上时跳过测试并给出提示；连得上但后续出错则应该让测试失败。"""
    probe_engine = create_engine(test_url.set(database=MAINTENANCE_DB_NAME), poolclass=NullPool)
    try:
        with probe_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:  # 只在数据库没启动、连不上时触发
        pytest.skip(
            f"连接不到 PostgreSQL 测试库（{test_url.host}:{test_url.port}）：{exc}。"
            "请先启动数据库，例如 `docker compose -f deploy/compose.yaml up -d`；"
            "CI 环境需要按开发文档第六步为流水线提供数据库服务。"
        )
    finally:
        probe_engine.dispose()


def _ensure_test_database_exists(test_url: URL) -> None:
    """测试库不存在就自动创建一个（库名已通过白名单校验，可以安全拼接）。"""
    admin_engine = create_engine(
        test_url.set(database=MAINTENANCE_DB_NAME),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": test_url.database},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    finally:
        admin_engine.dispose()


def _run_alembic_upgrade(test_url: URL) -> None:
    """在测试库上执行 ``alembic upgrade head``，表结构以迁移脚本为准。

    ``migrations/env.py`` 通过环境变量读取连接信息，所以在子进程里把 ``DB__*``
    全部覆盖成测试库，迁移不可能连到开发库。
    """
    overrides: dict[str, str] = {
        "DB__NAME": str(test_url.database),
        "DB__DRIVER": test_url.drivername,
    }
    if test_url.host:
        overrides["DB__HOST"] = test_url.host
    if test_url.port:
        overrides["DB__PORT"] = str(test_url.port)
    if test_url.username:
        overrides["DB__USERNAME"] = test_url.username
    if test_url.password:
        overrides["DB__HASHED_PASSWORD"] = test_url.password
    env: dict[str, str] = {**os.environ, **overrides}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BASE_DIR / "alembic.ini"), "upgrade", "head"],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"在测试库上执行迁移失败：\n{result.stdout}\n{result.stderr}")


def _reset_test_schema(engine: Engine) -> None:
    """清空测试库中由迁移创建的对象，保证「测前空库、测后无残留」。

    后续步骤新增 schema 时，记得把这里要清理的 schema 一起补上。
    """
    if engine.url.database != _test_db_name():
        raise RuntimeError(f"拒绝在非测试库 {engine.url.database!r} 上执行清理。")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS public.alembic_version"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """准备独立的测试库：建库 → 空库升级到 head → 测试结束再清空。"""
    test_url = _test_db_url()
    _skip_if_database_unavailable(test_url)
    _ensure_test_database_exists(test_url)

    test_engine = create_engine(test_url, poolclass=NullPool)
    _reset_test_schema(test_engine)
    try:
        _run_alembic_upgrade(test_url)
        yield test_engine
    finally:
        _reset_test_schema(test_engine)
        test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """每个测试一个独立事务，结束即回滚，测试库里不会留下任何数据。"""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        # 回滚之后确认真的清干净了：这是「每个测试结束后清理数据」的自动检查
        remaining_organizations = connection.execute(
            select(func.count()).select_from(Organization)
        ).scalar_one()
        remaining_users = connection.execute(select(func.count()).select_from(User)).scalar_one()
        connection.close()
        assert remaining_organizations == 0, "测试结束后测试库里仍残留组织数据，清理失败。"
        assert remaining_users == 0, "测试结束后测试库里仍残留用户数据，清理失败。"


@pytest.fixture
def api_client(db_session: Session) -> Iterator[TestClient]:
    """把应用里的 get_db 换成测试事务里的会话：接口和测试看到同一份数据"""

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
