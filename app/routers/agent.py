"""雪庐小账房：Microsoft Agent Framework Agent + 受登录保护的 AG-UI 端点。

对应第三天任务说明第六节：

- build_agent()：用官方 Python SDK（agent-framework）定义 Agent 的名称、指令、能力边界和工具。
- month_summary 工具：后端真实执行的只读查询，查「当前登录用户」某个月的收支汇总。
  身份来自 ContextVar（由已验证的 Bearer 令牌写入），模型无法指定用户 id。
- add_agent_endpoint()：用官方适配包 agent-framework-ag-ui 在 FastAPI 暴露 POST /agent，
  回复以 AG-UI 事件流（SSE）输出。鉴权放在 dependencies 里，401 在进入 Agent 之前抛出，
  模型不会被调用；authorization_scope_resolver 按登录用户隔离审批/会话作用域。
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request

from app.agent_config import AgentSettings
from app.agent_identity import current_agent_user_id
from app.deps import AuthContext, get_auth_context, unauthorized

logger = logging.getLogger(__name__)

AGENT_NAME = "xuelu-ledger-assistant"

AGENT_INSTRUCTIONS = """你是「雪庐小账房」，嵌在一个个人记账应用里的记账助手。

用途：帮登录用户看懂自己的账。

能力范围：
1. 回答通用问题（记账方法、预算建议等），用简体中文，语气平实克制。
2. 用户想知道自己某个月的收入、支出、结余时，调用 month_summary 工具查询该月汇总
   （month 参数格式 YYYY-MM，省略表示当月），然后基于工具的真实返回值作答。
3. 你只能查询汇总数字，不能增删改账目，也不要声称自己修改了数据。

规则：
- 涉及用户账目的数字必须来自 month_summary 的返回值，绝不编造。
- 工具返回失败或没有数据时如实说明，不要猜测。
- 不要索要或提及密码、令牌等凭证。
- 回答尽量简短，适合在小聊天面板里阅读。
"""


def _build_month_summary_tool():
    """构造只读工具；用户身份在执行时从请求上下文读取。"""
    from datetime import date

    from agent_framework import tool as maf_tool
    from sqlalchemy import select

    @maf_tool(
        name="month_summary",
        description=(
            "查询当前登录用户某个月的收支汇总（收入、支出、结余、笔数）。"
            "month 为 YYYY-MM 格式，省略则查当月。"
        ),
    )
    def month_summary(month: str | None = None) -> str:
        from app.db import SessionLocal
        from app.models import Entry

        user_id = current_agent_user_id.get()
        if user_id is None:
            # 正常路径下鉴权依赖已写入身份；走到这里说明上下文丢失，宁可拒绝。
            return "无法确认当前登录身份，已拒绝查询。"

        if month:
            try:
                year_str, _, month_str = month.partition("-")
                year, mon = int(year_str), int(month_str)
                if not (1 <= mon <= 12):
                    raise ValueError
            except ValueError:
                return f"月份格式不对：{month}，应为 YYYY-MM。"
        else:
            today = date.today()
            year, mon = today.year, today.month

        start = date(year, mon, 1)
        end = date(year + (mon == 12), (mon % 12) + 1, 1)

        with SessionLocal() as db:
            rows = db.scalars(
                select(Entry).where(
                    Entry.user_id == user_id,
                    Entry.occurred_on >= start,
                    Entry.occurred_on < end,
                )
            ).all()

        label = f"{year:04d}-{mon:02d}"
        if not rows:
            return f"{label} 没有任何账目记录。"
        income = sum(r.amount_cents for r in rows if r.kind == "income")
        expense = sum(r.amount_cents for r in rows if r.kind == "expense")
        return (
            f"{label} 汇总：收入 {income / 100:.2f} 元，支出 {expense / 100:.2f} 元，"
            f"结余 {(income - expense) / 100:.2f} 元，共 {len(rows)} 笔。"
        )

    return month_summary


def build_chat_client(settings: AgentSettings):
    """DeepSeek 等兼容服务走 OpenAI 的 /chat/completions，而不是新的 /responses。

    因此用 OpenAIChatCompletionClient；OpenAIChatClient 会请求 /v1/responses，
    DeepSeek 没有该端点，会直接 404。
    """
    from agent_framework.openai import OpenAIChatCompletionClient

    return OpenAIChatCompletionClient(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )


def build_agent(settings: AgentSettings):
    from agent_framework import Agent

    return Agent(
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        client=build_chat_client(settings),
        tools=[_build_month_summary_tool()],
    )


async def verify_agent_login(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
) -> None:
    """复用第二天的 Bearer 校验：失败抛 401，FastAPI 在进入端点前拦截，模型不会被调用。"""
    current_agent_user_id.set(context.user.id)
    request.state.ag_ui_user_id = context.user.id


def add_agent_endpoint(app: FastAPI, settings: AgentSettings) -> None:
    """注册受登录保护的 AG-UI 端点 POST /agent。"""
    from agent_framework_ag_ui import add_agent_framework_fastapi_endpoint

    agent = build_agent(settings)

    async def scope_resolver(request: Request) -> str:
        """AG-UI 授权作用域：按登录用户隔离，threadId 本身不是凭证。"""
        user_id = getattr(request.state, "ag_ui_user_id", None)
        if user_id is None:
            raise unauthorized()
        return f"ag-ui:user:{user_id}"

    add_agent_framework_fastapi_endpoint(
        app,
        agent=agent,
        path="/agent",
        dependencies=[Depends(verify_agent_login)],
        authorization_scope_resolver=scope_resolver,
        tags=["agent"],
    )
    logger.info("已注册 AG-UI 端点 POST /agent（模型 %s）", settings.model)
