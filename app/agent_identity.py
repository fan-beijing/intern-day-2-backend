"""当前请求的登录身份（请求级上下文变量）。

Agent 的工具需要知道「这次请求是谁在问」，但工具签名只能暴露模型可以填的参数（比如月份），
不能让模型传 user_id——否则模型（或伪造请求的人）就能读别人账本。

这里用 ContextVar 在「已通过 Bearer 校验的依赖」里写入用户 id，工具执行时读取。
因为一次 HTTP 请求（含其流式响应）在同一个 asyncio 任务里运行，工具拿到的必然是
本次请求自己的身份；并发请求各持一份上下文，不会互相覆盖。

对比另一种做法「每个请求重建一个绑定了 user_id 的 Agent 实例」：那需要把实例挂在
共享对象上并逐次替换，两个请求同时进来就会串号。ContextVar 没有共享可变状态。
"""

from __future__ import annotations

from contextvars import ContextVar

# None 表示「当前上下文没有已验证的登录身份」，工具遇到时必须拒绝而不是猜。
current_agent_user_id: ContextVar[int | None] = ContextVar(
    "current_agent_user_id", default=None
)
