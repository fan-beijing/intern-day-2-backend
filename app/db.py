"""数据库引擎与会话工厂。默认使用 SQLite，数据文件落在命名卷里。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _sqlite_path(database_url: str) -> Path | None:
    """从 SQLite URL 还原出文件路径；内存库或非 SQLite 返回 None。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None

    raw = database_url[len(prefix) :]
    if not raw or raw == ":memory:":
        return None
    # Windows 绝对路径会形如 /C:/dir/app.db，去掉前导斜杠交给 Path 处理
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    return Path(raw)


def _ensure_sqlite_dir(database_url: str) -> None:
    db_path = _sqlite_path(database_url)
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """容器启动时自动建表，不依赖人工进容器操作。"""
    from app import models  # noqa: F401  导入以注册模型元数据

    Base.metadata.create_all(bind=engine)
