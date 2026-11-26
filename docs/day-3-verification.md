# 第三天自测记录

> 记录时间：2026-11-25 起，2026-11-26 补测真实模型。命令与输出均为本机实际执行结果，未做修饰。
> 第 4 节是 **Mock 链路**（无额度时验证协议），第 5 节是 **真实模型**（阿里云百炼）。两者分开记录。

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

## 7. 真实模型的补测

第 4、5 节是 Mock 链路，只证明协议通。真实模型已在第 8 节补测完成：
流式回复、工具调用（数字与 `/ledger/summary` 一致）、多轮上下文三项均通过。


## 8. 真实模型（阿里云百炼 · deepseek-v4.1-flash）

前几节用 Mock 验证协议链路；本节换成真实模型复验，配置：

```ini
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_ID=deepseek-v4.1-flash
```

### 8.1 端点与鉴权行为不变

```
未登录 POST /agent -> 401 {"detail":"登录状态无效，请重新登录"}
```

换成真实模型后，鉴权仍然在进入 Agent **之前**完成，未登录请求不产生模型调用（不烧额度）。

### 8.2 真实模型主动调用工具

先记两笔真实账目，再问模型：

```
$ curl /ledger/summary?month=2026-11          # 后端权威值
{"month":"2026-11","income":0.0,"expense":180.3,"balance":-180.3,"count":2}

$ 提问「我这个月总共花了多少钱？请告诉我具体数字。」
→ 本月（2026-11）你的支出是 **180.30 元**，共 2 笔。
  收入 0.00 元，结余 -180.30 元。
```

事件序列里能看到完整的工具闭环：

```
RUN_STARTED
TOOL_CALL_START month_summary → TOOL_CALL_ARGS → TOOL_CALL_END → TOOL_CALL_RESULT
TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT ×13 → TEXT_MESSAGE_END
RUN_FINISHED
```

**180.30 与后端接口返回值完全一致**，说明工具是后端真实执行、结果真的回填给了模型，
不是模型编的数字。

补充：账目为空时问同一个问题，模型回答「本月（2026-11）还没有任何账目记录」，
也说明它读的是工具返回值而不是瞎猜。

### 8.3 真实模型多轮上下文

```
轮1：「你好，请记住，我叫阿雪，是个学数据的学生。」
     → 你好，阿雪。记下了——学数据的同学。

轮2（同一 threadId，带完整历史）：「我叫什么名字？是学什么的？」
     → 你叫阿雪，是学数据的学生。😊
```

浏览器里也复验了一遍（截图见前端仓库 `docs/screenshots/07-agent-real-model.png`）：

```
轮1：「我叫阿雪，平时最爱吃火锅。记住了吗？」
     → 记住了，阿雪，在这个对话里我会记着。……下次开新对话，可能就不记得了。

轮2：「我叫什么？爱吃什么？」
     → 你叫阿雪，最爱吃火锅。这是刚才你告诉我的，只在这个对话里记着。
```

模型还主动说明了「只在这个对话里记着、不会写进账本」，与实现一致
（历史在浏览器侧，后端不落库）。

### 8.4 结论

| 验证项 | 结果 |
| --- | --- |
| 真实模型流式回复 | ✅ 逐字到达，`TEXT_MESSAGE_CONTENT` 多块 |
| 真实模型触发只读工具 | ✅ 数字与 `/ledger/summary` 一致 |
| 真实模型多轮上下文 | ✅ 准确复述上一轮信息 |
| 鉴权仍在模型之前 | ✅ 未登录 401，零模型调用 |
