"""接口出入参定义。金额对外用「元」，落到库里换算成「分」。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

EntryKind = Literal["income", "expense"]


def _as_utc_iso(value: datetime) -> str:
    """库里存的是朴素 UTC，出参统一补上时区标记，避免前端按本地时间误读。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str, when_used="json")]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: UtcDateTime


class LoginResponse(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: UtcDateTime
    user: UserOut


class EntryCreate(BaseModel):
    kind: EntryKind
    amount: float = Field(gt=0, le=1_000_000, description="正数，单位元，最多两位小数")
    category: str = Field(default="其他", min_length=1, max_length=20)
    note: str = Field(default="", max_length=200)
    occurred_on: date | None = None


class EntryOut(BaseModel):
    id: int
    kind: EntryKind
    amount: float
    category: str
    note: str
    occurred_on: date
    created_at: UtcDateTime


class EntryList(BaseModel):
    month: str
    count: int
    items: list[EntryOut]


class SummaryOut(BaseModel):
    month: str
    income: float
    expense: float
    balance: float
    count: int


class MessageOut(BaseModel):
    detail: str
