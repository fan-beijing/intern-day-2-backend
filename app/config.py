"""运行配置：从环境变量或仓库根目录的 .env 读取。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class ConfigError(RuntimeError):
    """配置缺失时抛出，交由入口打印可操作的提示。"""


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
        )
        self.session_ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "120"))
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
            if origin.strip()
        ]
        self.seed_username = os.getenv("SEED_USERNAME", "demo")
        self.seed_password = os.getenv("SEED_PASSWORD", "")

    def validate(self) -> None:
        if not self.seed_password:
            raise ConfigError(
                "缺少 SEED_PASSWORD 环境变量。请在仓库根目录执行 "
                "`cp .env.example .env`，并把 SEED_PASSWORD 改成自己的练习密码后重启服务。"
            )
        if len(self.seed_password) > 72:
            raise ConfigError("SEED_PASSWORD 不能超过 72 字节（bcrypt 的输入上限）。")
        if self.session_ttl_minutes <= 0:
            raise ConfigError("SESSION_TTL_MINUTES 必须是正整数。")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
