"""鉴权依赖：解析 Bearer 令牌，校验会话是否有效。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthSession, User, utcnow
from app.security import hash_token

bearer_scheme = HTTPBearer(auto_error=False, description="登录后拿到的令牌")

UNAUTHORIZED_DETAIL = "登录状态无效，请重新登录"


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise unauthorized()

    auth_session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(credentials.credentials))
    )
    if auth_session is None:
        raise unauthorized()

    if auth_session.expires_at <= utcnow():
        # 过期行顺手清掉，避免会话表无限增长
        db.delete(auth_session)
        db.commit()
        raise unauthorized()

    user = db.get(User, auth_session.user_id)
    if user is None:
        db.delete(auth_session)
        db.commit()
        raise unauthorized()

    return AuthContext(user=user, session=auth_session)


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user
