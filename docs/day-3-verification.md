# 第三天自测记录

> 记录时间：2026-11-25。命令与输出均为本机实际执行结果，未做修饰。
> 真实模型（DeepSeek）部分待密钥到位后补测，下方明确区分 **Mock 链路** 与 **真实模型**。

## 1. 环境

| 项 | 值 |
| --- | --- |
| Python | 3.13.14 |
| agent-framework-core | 1.26.0 |
| agent-framework-ag-ui | 1.8.1 |
| agent-framework-openai | 1.18.2 |
| CopilotKit（react-core / react-ui / runtime） | 1.90.2 |
| Node | 22.22.2 |
| FastAPI | 0.162.2 |

## 2. 既有功能未被破坏

```
$ .venv/Scripts/python.exe -m pytest -q
................                                                          [100%]
```

16 条用例全部通过（登录、当前用户、退出、凭证过期、越权删除、按月查询与汇总）。

## 3. 端点注册与鉴权（在模型之前拦截）

用无效的模型地址启动，确认 `/agent` 已注册且未登录被拒：

```
paths: ['/', '/agent', '/auth/login', '/auth/logout', '/auth/me', '/health',
        '/ledger/entries', '/ledger/entries/{entry_id}', '/ledger/summary']
未登录 POST /agent -> 401 {"detail":"登录状态无效，请重新登录"}
```

要点：`401` 来自 `dependencies`，此时还没有构造模型请求，因此**不会产生任何模型调用**。

## 4. Mock 链路（非真实模型）

为在没有密钥的情况下验证协议与工具链路，用 `Mock` 的 OpenAI 兼容服务（`/v1/chat/completions`，支持流式与 tool_calls）替代真实模型。
**这一节的结论只证明链路通，不代表模型能力**。

带登录令牌请求 `/agent`，实际收到的 AG-UI 事件序列：

```
RUN_STARTED
TEXT_MESSAGE_START
TOOL_CALL_START month_summary
TOOL_CALL_ARGS
TOOL_CALL_END
TOOL_CALL_RESULT
TEXT_MESSAGE_END
TEXT_MESSAGE_START
TEXT_MESSAGE_CONTENT ×N
TEXT_MESSAGE_END
MESSAGES_SNAPSHOT
RUN_FINISHED
```

拼接后的回复内容：

```
2026-11 汇总：收入 1200.00 元，支出 3200.00 元，结余 -2000.00 元，共 2 笔。
```

说明三件事：工具被真实调用、工具按登录用户查库、工具结果回到了 Agent 的下一轮输入。

## 5. 浏览器端到端（Mock 链路）

真实 Chrome 走完登录 → 提问 → 流式回复：

| 检查 | 结果 |
| --- | --- |
| 未登录访问 /ledger | 重定向到 /login |
| 登录后出现「雪庐小账房」面板 | 是 |
| 发送「我这个月花了多少？」 | 收到流式回复，数字与库中一致 |
| 页面 JS 报错 | 无 |

截图：`docs/screenshots/day-3-agent-chat.png`（待补，见第 7 节）

## 6. 踩到并修掉的两个问题

1. **模型端点不匹配**：`OpenAIChatClient` 请求 `/v1/responses`，DeepSeek 只有 `/v1/chat/completions`，导致 `ChatClientException 404`。
   改用 `OpenAIChatCompletionClient` 后正常。
2. **前后端路由模式不一致**：前端 `useSingleEndpoint`，Runtime 默认 `multi-route`，请求打到 `/api/copilotkit` 直接 404。
   Runtime 显式设置 `mode: "single-route"` 后一致。

## 7. 待补

- [ ] 真实 DeepSeek 模型的流式回复与工具调用（替换 `MODEL_API_KEY` 后重跑第 4、5 节）
- [ ] 两轮上下文（第一轮告知虚构昵称，第二轮追问）
- [ ] 容器（两个 Compose 项目）联调
- [ ] 上述三项的截图
