"""本地 Mock 模型服务（OpenAI 兼容），仅用于在无模型额度时验证协议链路。

它不是"假打字"：这是一个真的 HTTP 服务，`/v1/chat/completions` 真的按 SSE
逐块推送 `chat.completion.chunk`，并且真的会返回 `tool_calls`——Agent Framework
收到后真的去执行 month_summary 工具、拿到真实数据库结果、再发第二次请求回来。
因此这条链路验证的是：流式增量事件、工具调用闭环、AG-UI 事件转换、前端逐步渲染。

**它不验证**：真实模型的语义理解与回答质量。凡是基于 Mock 的结论，
README / PR 里都必须标注 Mock，不能写成"真实模型测试通过"。

用法：
    python scripts/mock_model_server.py            # 默认 8899 端口
    MODEL_BASE_URL=http://127.0.0.1:8899/v1 MODEL_ID=mock-model

仅绑定 127.0.0.1，不对外暴露。
"""

from __future__ import annotations

import json
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock OpenAI-compatible model server", docs_url=None, redoc_url=None)

MODEL_ID = "mock-model"


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


LEDGER_KEYWORDS = ("花", "支出", "收入", "结余", "账", "收支", "多少钱", "汇总")


def _is_ledger_question(text: str) -> bool:
    return any(k in text for k in LEDGER_KEYWORDS)


def _wants_tool(messages: list[dict[str, Any]]) -> bool:
    """只在"这一轮"用户问账目相关问题时调用工具（模拟模型的判断，而不是无脑调）。"""
    if any(m.get("role") == "tool" for m in messages):
        # 本轮已经拿到工具结果，不再重复调用
        return False

    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return False
    return _is_ledger_question(str(user_msgs[-1].get("content", "")))


def _reply_text(messages: list[dict[str, Any]]) -> str:
    """结合工具结果生成回答；工具结果来自后端真实执行的 month_summary。"""
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    user_msgs = [m for m in messages if m.get("role") == "user"]
    last_user = str(user_msgs[-1].get("content", "")) if user_msgs else ""

    # 多轮上下文验证：让模型"记住"用户在前一轮告诉它的昵称
    nickname = ""
    for m in user_msgs[:-1]:
        text = str(m.get("content", ""))
        for marker in ("我叫", "昵称是", "叫我"):
            if marker in text:
                nickname = text.split(marker, 1)[1].strip(" 。，,.")
                break
        if nickname:
            break

    # 本轮拿到了工具结果，就基于真实数字回答
    if tool_msgs:
        summary = str(tool_msgs[-1].get("content", "")).strip()
        head = f"（Mock 服务）我查到了：{summary}"
        if nickname:
            head += f"\n另外，你之前说想被叫做「{nickname}」。"
        return head

    # 本轮是自我介绍 / 追问名字
    if nickname and ("什么" in last_user or "叫" in last_user):
        return f"（Mock 服务）你上一轮告诉我，希望被叫做「{nickname}」。"

    return (
        "（Mock 服务）收到。这是本地 Mock 模型返回的流式文本，"
        "用来验证 AG-UI 事件流与前端逐字渲染；不代表真实模型能力。"
    )


def _stream(messages: list[dict[str, Any]]):
    yield _chunk({"role": "assistant", "content": ""})

    if _wants_tool(messages):
        # 真的返回 tool_calls，让 Agent Framework 去执行后端工具
        yield _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_mock_1",
                        "type": "function",
                        "function": {"name": "month_summary", "arguments": "{}"},
                    }
                ]
            }
        )
        yield _chunk({}, finish_reason="tool_calls")
        yield "data: [DONE]\n\n"
        return

    text = _reply_text(messages)
    # 按小块推送，模拟真实模型的 token 流；每块之间留一点间隔便于肉眼观察
    step = 6
    for i in range(0, len(text), step):
        yield _chunk({"content": text[i : i + step]})
        time.sleep(0.02)
    yield _chunk({}, finish_reason="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    if body.get("stream"):
        return StreamingResponse(_stream(messages), media_type="text/event-stream")
    # 非流式：拼出完整回复（Agent 用不到，但保持兼容）
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _reply_text(messages)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local-mock"}]}


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


if __name__ == "__main__":
    import os

    # 本机直接跑时默认只听 127.0.0.1；在容器里需要被同项目的 api 访问，
    # 所以绑定地址做成可配置（compose.mock.yaml 里设为 0.0.0.0）。
    host = os.getenv("MOCK_HOST", "127.0.0.1")
    port = int(os.getenv("MOCK_PORT", "8899"))
    uvicorn.run(app, host=host, port=port, log_level="warning")
