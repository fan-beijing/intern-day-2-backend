"""应用入口：装配路由、CORS，启动时建表并创建练习账号。"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ConfigError, settings
from app.db import SessionLocal, init_db
from app.routers import auth, ledger
from app.seed import ensure_seed_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings.validate()
    except ConfigError as exc:
        # 直接给出可操作的指引，而不是抛一串 traceback
        print(f"[启动失败] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    init_db()
    with SessionLocal() as db:
        created = ensure_seed_user(db)
    if created:
        print(f"[启动] 已创建练习账号 {created}")
    yield


app = FastAPI(
    title="记账本后端",
    version="1.0.0",
    description="登录鉴权 + 个人记账接口",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ledger.router)


@app.get("/health", tags=["meta"], summary="健康检查")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["meta"], summary="服务自述")
def root() -> dict[str, object]:
    return {
        "service": "intern-day-2-backend",
        "docs": "/docs",
        "endpoints": ["/auth/login", "/auth/me", "/auth/logout", "/ledger/entries", "/ledger/summary"],
    }
