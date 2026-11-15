"""密码哈希与不透明令牌的生成 / 校验。

bcrypt 5.x 对超过 72 字节的输入会直接抛异常，所以入口处统一按字节截断，
避免用户输入超长密码时接口 500。
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt

BCRYPT_MAX_BYTES = 72
TOKEN_BYTES = 32


def _as_bcrypt_input(raw: str) -> bytes:
    return raw.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(_as_bcrypt_input(raw_password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_as_bcrypt_input(raw_password), password_hash.encode("utf-8"))
    except ValueError:
        # 哈希字段被写坏时按校验失败处理，不把内部异常抛给调用方
        return False


def new_token() -> str:
    """生成不透明随机令牌，明文只返回给客户端一次。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """会话表只存令牌的 SHA-256 摘要，库被读走也无法直接冒用。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# 用户不存在时也走一次 bcrypt 校验，避免通过响应时间判断账号是否存在
DUMMY_PASSWORD_HASH = hash_password("timing-equalizer-not-a-real-password")
