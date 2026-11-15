"""登录、当前用户、退出登录。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import AuthContext, get_auth_context
from app.models import AuthSession, User, utcnow
from app.schemas import LoginRequest, LoginResponse, MessageOut, UserOut
from app.security import DUMMY_PASSWORD_HASH, hash_token, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# 账号不存在与密码错误返回同一句提示，不泄露账号是否存在
BAD_CREDENTIALS = "账号或密码错误"


def _bad_credentials() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=BAD_CREDENTIALS)


def _to_user_out(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, created_at=user.created_at)


@router.post("/login", response_model=LoginResponse, summary="账号密码登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.username == payload.username))

    if user is None:
        # 依然算一次哈希，抹平「账号不存在」与「密码错误」的响应时间差
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        raise _bad_credentials()

    if not verify_password(payload.password, user.password_hash):
        raise _bad_credentials()

    token = new_token()
    expires_at = utcnow() + timedelta(minutes=settings.session_ttl_minutes)
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    db.commit()

    return LoginResponse(token=token, expires_at=expires_at, user=_to_user_out(user))


@router.get("/me", response_model=UserOut, summary="获取当前登录用户")
def read_me(context: AuthContext = Depends(get_auth_context)) -> UserOut:
    return _to_user_out(context.user)


@router.post("/logout", response_model=MessageOut, summary="退出登录并作废当前令牌")
def logout(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageOut:
    db.delete(context.session)
    db.commit()
    return MessageOut(detail="已退出登录")
