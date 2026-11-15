"""练习账号初始化：容器启动时自动建表并写入一个账号。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.security import hash_password


def ensure_seed_user(db: Session) -> str | None:
    """没有该账号就创建，返回新建的用户名；已存在返回 None。"""
    exists = db.scalar(select(User).where(User.username == settings.seed_username))
    if exists is not None:
        return None

    db.add(
        User(
            username=settings.seed_username,
            password_hash=hash_password(settings.seed_password),
        )
    )
    db.commit()
    return settings.seed_username
