"""自选功能：个人账目的新增、按月列表、删除、月度汇总。

所有查询强制带 user_id；操作他人的账目一律返回 404，不暴露该记录是否存在。
"""

from __future__ import annotations

import calendar
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Entry, User
from app.schemas import EntryCreate, EntryList, EntryOut, SummaryOut

router = APIRouter(prefix="/ledger", tags=["ledger"])

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def _month_range(month: str) -> tuple[date, date]:
    year, mon = int(month[:4]), int(month[5:7])
    last_day = calendar.monthrange(year, mon)[1]
    return date(year, mon, 1), date(year, mon, last_day)


def _resolve_month(month: str | None) -> str:
    today = date.today()
    resolved = month or f"{today.year:04d}-{today.month:02d}"
    try:
        _month_range(resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="month 参数格式应为 YYYY-MM",
        ) from exc
    return resolved


def _to_entry_out(entry: Entry) -> EntryOut:
    return EntryOut(
        id=entry.id,
        kind=entry.kind,  # type: ignore[arg-type]
        amount=round(entry.amount_cents / 100, 2),
        category=entry.category,
        note=entry.note or "",
        occurred_on=entry.occurred_on,
        created_at=entry.created_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账目不存在")


@router.post(
    "/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增账目",
)
def create_entry(
    payload: EntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntryOut:
    amount_cents = int(round(payload.amount * 100))
    if amount_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="金额必须大于 0",
        )

    entry = Entry(
        user_id=current_user.id,
        kind=payload.kind,
        amount_cents=amount_cents,
        category=payload.category,
        note=payload.note,
        occurred_on=payload.occurred_on or date.today(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_entry_out(entry)


@router.get("/entries", response_model=EntryList, summary="按月查看本人账目")
def list_entries(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN, description="YYYY-MM，默认当月"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntryList:
    resolved = _resolve_month(month)
    start, end = _month_range(resolved)

    rows = db.scalars(
        select(Entry)
        .where(
            Entry.user_id == current_user.id,
            Entry.occurred_on >= start,
            Entry.occurred_on <= end,
        )
        .order_by(Entry.occurred_on.desc(), Entry.id.desc())
    ).all()

    items = [_to_entry_out(row) for row in rows]
    return EntryList(month=resolved, count=len(items), items=items)


@router.get("/summary", response_model=SummaryOut, summary="月度收支汇总")
def summarize(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN, description="YYYY-MM，默认当月"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryOut:
    resolved = _resolve_month(month)
    start, end = _month_range(resolved)

    rows = db.execute(
        select(Entry.kind, func.coalesce(func.sum(Entry.amount_cents), 0))
        .where(
            Entry.user_id == current_user.id,
            Entry.occurred_on >= start,
            Entry.occurred_on <= end,
        )
        .group_by(Entry.kind)
    ).all()

    totals = {kind: int(total) for kind, total in rows}
    income = totals.get("income", 0) / 100
    expense = totals.get("expense", 0) / 100

    count = db.scalar(
        select(func.count(Entry.id)).where(
            Entry.user_id == current_user.id,
            Entry.occurred_on >= start,
            Entry.occurred_on <= end,
        )
    )

    return SummaryOut(
        month=resolved,
        income=round(income, 2),
        expense=round(expense, 2),
        balance=round(income - expense, 2),
        count=int(count or 0),
    )


@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除本人账目",
)
def delete_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    entry = db.scalar(
        select(Entry).where(Entry.id == entry_id, Entry.user_id == current_user.id)
    )
    if entry is None:
        # 他人账目与不存在返回同一个 404
        raise _not_found()

    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
