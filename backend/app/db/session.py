from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.settings import settings

engine = create_engine(settings.db.url, pool_pre_ping=True)

# expire_on_commit: commit之后对象属性还能读，接口返回响应时不会被提前置空
SessionLocal = sessionmaker(expire_on_commit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖: 每个请求一个数据库会话，请求结束（含异常）自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
