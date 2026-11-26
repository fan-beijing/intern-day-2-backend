# 第三天：Agent 交互原理说明

> 本文回答任务说明第四节列出的 8 个问题，并记录今天实际使用的版本、参考链接、
> 仍不理解的问题，以及一个只有自己调试才弄懂的细节。
>
> 写作原则：只写我自己跑通、看过日志或抓过事件的结论。凡是没验证的，标注"未验证"。

---

## 0. 先给一句话结论

今天这条链路是三层各管一件事：

- **Microsoft Agent Framework**：后端真正"活着"的那个 Agent——它决定调不调模型、调不调工具、怎么组织提示词。
- **AG-UI**：前后端之间的**事件协议**（用什么形状的 JSON 描述"开始跑了""文字多了几个字""工具调用了""失败了"）。
- **CopilotKit**：前端和 Runtime 侧的**接线层**，把浏览器里的聊天 UI 和 AG-UI 事件流接起来。

最容易搞混的一点：**AG-UI 不是传输方式**。它规定的是"事件长什么样"，跑在 HTTP 上的 SSE 这条管道里。协议和管道是两件事。

---

## 1. Microsoft Agent Framework 解决什么问题？Agent、模型、工具是什么关系？

**它解决的是"Agent 的骨架"问题**，而不是"怎么调用模型"这一个动作。

如果不用框架，我得自己写：拼接多轮消息历史、判断模型返回的是文本还是工具调用、
执行工具、把工具结果塞回对话再请求一次模型、处理流式增量、处理异常和重试。
这些逻辑每次都长得差不多，但每写一遍都会漏一点。

Agent Framework 把这件事抽象成四个角色：

| 角色 | 职责 | 本项目里的具体对象 |
| --- | --- | --- |
| **Agent** | 有名字、有指令（instructions）、有工具集、有模型客户端的一个"执行单元" | `Agent(name="xuelu-ledger-assistant", instructions=..., client=..., tools=[...])` |
| **Chat Client** | 真正和模型服务通信的适配器，负责把 Agent 的消息变成该服务商的请求格式 | `OpenAIChatClient(model=..., api_key=..., base_url=...)` |
| **Tool** | 一个普通 Python 函数，用 `@tool` 装饰后，模型能看到它的名字、说明和参数 | `month_summary(month: str \| None = None) -> str` |
| **Runtime/编排** | 掌握"这一轮该不该调工具、调用几次、什么时候停"的循环 | 框架内部的 `_pull_next_update()` 循环 |

**三者的关系**，用一次真实请求来说明：

1. Agent 带着 instructions 和历史消息，交给 Chat Client。
2. Chat Client 发给模型服务（本项目是 DeepSeek 的 OpenAI 兼容接口）。
3. 模型如果认为需要数据，会返回一个"我要调用 `month_summary`，参数 month=2026-11"的意图。
4. **框架**（不是模型）执行这个 Python 函数，拿到文本结果。
5. 框架把结果作为一条工具消息追加进对话，**再请求一次模型**。
6. 模型这次基于真实数字生成自然语言回答。

第 4 步是我今天最想强调的：**工具是后端真的执行了**，不是模型"说"它执行了。
任务说明明确禁止把"工具执行成功"写死在回复里，原因就在这里——模型只是提出请求，
执行权在后端代码手上。

**我为什么选 DeepSeek 而不是 OpenAI**：DeepSeek 提供 OpenAI 兼容接口，
所以官方 `OpenAIChatClient` 加一个 `base_url` 就能用，不需要自己写适配器。
这也是 README 里写"换服务商只改三个环境变量"的依据。

---

## 2. CopilotKit 在 React 应用里做什么？和自己手写输入框有什么区别？

**它做两件事：管 UI 状态，管协议对接。**

如果我自己手写一个聊天框，我需要处理：

- 消息列表的增删和渲染（用户消息、助手消息、工具调用气泡）
- 输入框的禁用、发送中状态、失败重试
- **最难的部分**：把 AG-UI 的事件流（`RUN_STARTED` / `TEXT_MESSAGE_CONTENT` / `RUN_FINISHED`）
  解析成"第 3 条消息的文字又多了 12 个字"这种增量更新
- 中断、取消、新建会话
- 和 Runtime 的握手、Header 透传

CopilotKit 把这些封装成 `<CopilotKitProvider>` + `<CopilotChat>` 两个组件。
本项目里实际就是这么用的：

```tsx
<CopilotKitProvider runtimeUrl="/api/copilotkit" headers={headers} onError={handleError} useSingleEndpoint>
  <CopilotChat agentId="xuelu-ledger-assistant" threadId={threadId} labels={{...}} />
</CopilotKitProvider>
```

**区别的本质**：手写输入框我控制一切，但我得自己实现 SSE 解析和增量合并；
用 CopilotKit 我少写几百行，代价是要接受它的组件结构、版本升级带来的 API 变动，
以及"出问题时错误被它吞掉一层"。

今天真实踩到的例子：`useSingleEndpoint`、`agentId`、`threadId` 这些 prop 都是
1.90.2 这个版本才有的形状。任务说明特意提醒"不能混用不同版本的导入路径"，
原因就是 CopilotKit 从 1.x 到 v2 的 API 差异很大——我这个项目用的是
`@copilotkit/react-core/v2` 这个子路径导出，而不是包根。

---

## 3. AG-UI 是什么？与普通 JSON 接口、HTTP、SSE 是什么关系？

**AG-UI 是一套"事件协议"**：它规定前后端在一次 Agent 运行中交换哪些事件、
每个事件的 JSON 长什么样。它**不规定**用什么传输。

这三层要分清楚，我在演示时会重点讲：

```
┌─────────────────────────────────────────────┐
│  AG-UI 协议（事件语义层）                      │
│  RUN_STARTED / TEXT_MESSAGE_CONTENT /          │
│  TOOL_CALL_START / TOOL_CALL_RESULT /          │
│  RUN_FINISHED / RUN_ERROR                      │
│  → 规定"说什么"，不规定"怎么说"                │
├─────────────────────────────────────────────┤
│  SSE（传输方式）                               │
│  text/event-stream, "data: {...}\n\n"         │
│  → 规定"怎么分帧、怎么持续推"                   │
├─────────────────────────────────────────────┤
│  HTTP（更底层）                                │
│  POST /agent, 请求头, 状态码                    │
│  → 规定"怎么建立这次连接"                       │
└─────────────────────────────────────────────┘
```

**和普通 JSON 接口的区别**：普通接口是"一问一答"，响应头 `Content-Type: application/json`，
服务端算完一次性返回。AG-UI 端点是一问**持续多答**，响应头是 `text/event-stream`，
服务端算一点推一点。

**SSE 和 WebSocket 的区别**（任务说明特意点名，不能写错）：

| | SSE | WebSocket |
| --- | --- | --- |
| 方向 | 服务端 → 客户端单向 | 双向 |
| 底层 | 就是普通 HTTP 响应，只是不结束 | 独立协议，先 upgrade 握手 |
| 实现 | 一个 `POST` 请求就够了 | 需要 `ws://` 连接管理 |
| 本项目 | **用的就是这个** | 没用 |

今天的链路里，浏览器发一个问题是一个普通的 `POST /api/copilotkit`，
响应用 SSE 持续推事件。**全程没有 WebSocket。**

**实测证据**（我自己用 curl 打的，不是推测）：

```
$ curl -X POST http://127.0.0.1:8123/agent -H "Authorization: Bearer <token>" -d '{...}'
HTTP 200
data: {"type":"RUN_STARTED","threadId":"t1","runId":"r1"}

data: {"type":"RUN_ERROR","message":"An internal error has occurred while streaming events.","code":"ChatClientException"}
```

`data: {...}\n\n` 这个格式就是 SSE。`RUN_STARTED` 是 AG-UI 的事件类型。
同一次响应里先来 `RUN_STARTED` 后来 `RUN_ERROR`，说明**失败是在事件流内部报告的**，
不是靠 HTTP 状态码——这一点直接影响前端怎么写错误处理（见第 6 问）。

---

## 4. 从用户点击发送到浏览器显示回复，消息经过哪些组件？

这是我最想讲清楚的一张表。**每一站收到什么、返回什么**：

| # | 组件 | 收到 | 返回/发出 |
| --- | --- | --- | --- |
| 1 | 用户 | 在输入框敲字，按发送 | 一条 `UserMessage` |
| 2 | `CopilotChat`（React） | 用户消息 + 当前 `threadId` | 一个 HTTP 请求，准备发往 Runtime |
| 3 | `CopilotKitProvider` | 上述请求 + `runtimeUrl` + `headers` | 附加 `Authorization: Bearer <登录令牌>` 后发 `POST /api/copilotkit` |
| 4 | **Vite 开发服务器** | 同源的 `/api/copilotkit` 请求 | **同源代理**转发到 `http://runtime:4000`（容器内） |
| 5 | **CopilotKit Runtime**（Express） | 浏览器请求（含 Authorization） | 构造 `HttpAgent({url, headers})`，转成 AG-UI 请求发 `POST /agent` |
| 6 | **FastAPI 鉴权依赖** | `Authorization` 头 | 查会话表：有效→取出 user，写入 ContextVar；无效→**抛 401，流程终止** |
| 7 | **AG-UI 适配层** | AG-UI 请求体（messages / threadId / runId） | 装配成 Agent Framework 的调用，开始 SSE 输出 |
| 8 | **Agent Framework** | instructions + 消息历史 | 调 Chat Client |
| 9 | **Chat Client** | 消息 | OpenAI 格式请求 → DeepSeek |
| 10 | **模型服务** | 请求 | 文本增量，或"要调工具"的意图 |
| 11 | **Agent Framework** | 模型意图 | 如果是工具：执行 `month_summary()`，读数据库，拿回字符串 |
| 12 | 同上 | 工具结果 | 追加进对话，**再请求一次模型** |
| 13 | **模型服务** | 带工具结果的完整对话 | 最终文本，流式增量 |
| 14 | **AG-UI 适配层** | 框架的增量更新 | 转成 AG-UI 事件 `TEXT_MESSAGE_CONTENT` 等，写进 SSE |
| 15 | 原路返回 | SSE 事件 | Runtime → Vite 代理 → 浏览器 |
| 16 | `CopilotChat` | 增量事件 | 逐步更新消息气泡 |

**关键点**：第 4 步和第 5 步是很多人会漏掉的。Vite **不是** Runtime，
它只是个带代理的静态服务器。Runtime 是另一个独立的 Node 进程。
少了 Runtime，浏览器直接打 `/agent` 会遇到 CORS，而且拿不到 CopilotKit 的会话管理。

---

## 5. CopilotKit Runtime 部署在哪、做什么、怎么连 Python Agent？Vite 为什么不能当 Runtime？

**部署位置**：在前端仓库里，是一个独立的 Node 进程（本项目的 `server/runtime.mjs`，
用 Express 托管），容器里是 compose 的第二个服务 `runtime`，监听 4000。

**它做什么**（三件）：

1. **协议转换**：把 CopilotKit 前端 SDK 的请求，转成对 `POST /agent` 的 AG-UI 请求。
   实现上是 `new HttpAgent({ url: BACKEND_AGENT_URL, headers: {Authorization} })`。
2. **凭证透传**：按请求取出浏览器的 `Authorization` 头，原样转给后端。
   **Runtime 自己不存任何用户凭证**，也不是"拿一个管理员 token 替所有人调用"。
   这一点任务说明明确禁止，我在代码注释里也写死了。
3. **会话管理**：`threads: { access: 'owner' }`，会话 id 本身就是访问凭证，
   未识别的调用方不能列举别人的会话。

**怎么连 Python Agent**：`HttpAgent` 指向 `BACKEND_AGENT_URL`。
本机开发是 `http://localhost:8000/agent`；容器里因为**两个 Compose 项目互不相识**，
默认走 `http://host.docker.internal:8000/agent`（经宿主机映射端口），
而不是假定 `api` 这个服务名可解析。

**Vite 为什么不能当 Runtime**：

- Vite 的职责是编译 TSX、提供 HMR、发静态文件。它**没有** AG-UI 协议实现。
- Vite 的 `proxy` 只是转发 HTTP，不理解 SSE 之外的任何 AG-UI 语义，也不做 Agent 注册。
- CopilotKit 的会话/线程状态需要 Runtime 进程持有，Vite 没有这个状态。

**为什么还留着 Vite 的代理？** 为了让浏览器**同源**访问 `/api/copilotkit`，
避免跨域和预检，也避免浏览器需要知道 Runtime 的真实端口。这是个工程便利，
不是"Vite 兼任 Runtime"。这两件事我在交互图上会分开画。

---

## 6. 流式回复如何逐步显示？开始、增量、结束、失败怎么被前端识别？

**逐步显示的原理**：模型是 token 流式输出的；框架把每个增量包成 AG-UI 事件；
适配层立刻写进 SSE 响应（`keepalive_seconds=15` 防止中间空闲被断）；
前端 SDK 收到 `TEXT_MESSAGE_CONTENT` 就往对应消息上追加文字，触发 React 重渲染。

事件类型我实际见到的：

| 事件 | 含义 | 前端动作 |
| --- | --- | --- |
| `RUN_STARTED` | 这次运行开始，带 threadId / runId | 显示"发送中"，锁定输入 |
| `TEXT_MESSAGE_START` | 一条新消息开始 | 创建气泡 |
| `TEXT_MESSAGE_CONTENT` | 文本增量 | **追加文字**（这就是"逐步显示"） |
| `TOOL_CALL_START` / `TOOL_CALL_RESULT` | 工具调用的中间态 | 可显示"正在查询…" |
| `RUN_FINISHED` | 正常结束 | 解锁输入，隐藏"发送中" |
| `RUN_ERROR` | 运行期失败 | 显示错误，**结束等待** |

**一个我实际踩到的坑，必须在演示时讲**：

失败有两种，处理方式完全不同：

1. **建立事件流之前就失败**（比如没登录）→ HTTP 状态码 `401`。
   这时前端拿到的是普通 HTTP 错误，走 `onError` / 请求异常分支。
2. **事件流已经开始之后失败**（比如模型 key 无效）→
   **HTTP 仍然是 200**，错误藏在 SSE 里的一条 `RUN_ERROR` 事件中。

我在探针里实测到的就是第 2 种：HTTP 200，然后 `data: {"type":"RUN_ERROR",...}`。
如果只判断 HTTP 状态码，前端会永远转圈——因为 200 看起来是成功的。
这就是任务说明"事件流已开始后出现运行错误时，处理所选 SDK 的错误事件"的具体含义。

**防缓冲**：SSE 最容易被中间层（反向代理、某些网关）攒着，等结束一次性吐出来，
表现就是"等很久，然后整段出现"——任务说明点名的"假打字"。本项目的应对：
Vite 代理不开 ws、不缓冲；Runtime 直接 pipe 后端的响应流。

---

## 7. 登录凭证和模型 API Key 分别谁保存、发给谁？为什么模型密钥不能进浏览器？

这两个凭证**完全不同**，混在一起就是事故：

| | 登录凭证（Bearer 令牌） | 模型 API Key |
| --- | --- | --- |
| 谁签发 | 本项目后端 `/auth/login` | 模型服务商（DeepSeek / OpenAI） |
| 存哪 | 浏览器 `localStorage`（前端）+ 后端会话表只存 SHA-256 摘要 | **只在后端容器的环境变量** |
| 发给谁 | 每次请求发给**本项目的后端**（经 Runtime 透传） | 只发给模型服务商 |
| 生命周期 | 120 分钟，退出即失效 | 长期，按额度计费 |
| 泄露后果 | 别人能读你的账 | **别人能刷你的钱**，且能拿到你们公司所有用量 |

**为什么模型 key 绝不能进浏览器**：

1. 前端代码、`localStorage`、`Network` 面板、Source Map、打包产物，全部对用户可见。
   只要进了一次浏览器，就等于公开。
2. 任务说明明确禁止写进"镜像构建参数、代码或前端环境变量"——因为
   `VITE_*` 前缀的变量会被**编译进 JS 产物**，`docker build --build-arg` 的值
   会留在镜像历史里，`docker history` 就能看到。
3. 模型调用必须由后端发起，这样才有一个**可信的中间层**去做：身份校验、
   限流、审计日志、按用户隔离数据。

本项目的具体做法：`AgentSettings` 只从 `os.getenv` 读，`.env` 在 `.gitignore` 里，
`.dockerignore` 排除 `.env`，`compose.yaml` 用 `env_file` 注入而不是 `build-arg`。
前端 `.env.example` 里只有 Runtime 地址这类**非敏感**配置。

---

## 8. 对话上下文从哪来？登录会话和 thread/run 标识有什么区别？退出或换账号怎么办？

**上下文来源**：由**浏览器**持有并每次全量带上。每次请求的 `messages` 数组
就是完整历史，后端不存对话历史（今天不做数据库持久化）。

**三个 id，职责完全不同，绝对不能混**：

| 标识 | 谁产生 | 作用 | 是不是凭证 |
| --- | --- | --- | --- |
| **登录会话令牌** | 后端 `/auth/login` | 证明"你是哪个用户" | **是**，决定你能读谁的数据 |
| **threadId** | 前端（`crypto.randomUUID()`） | 把多轮消息归到同一个对话 | **不是**，只是分组标签 |
| **runId** | 每次运行 | 标识"这一次提问"，用于中断/关联事件 | 不是 |

**为什么不能把 threadId 当凭证**：threadId 是前端自己生成的随机串，
如果后端仅凭"我知道这个 threadId"就返回历史，那么随便猜/泄露一个 threadId
就能读别人的对话。任务说明第十节专门写了这条。本项目的防线是：
**后端只认 Bearer 令牌**，threadId 只影响会话分组，不影响数据权限；
工具查询用户数据时，user_id 来自**已验证的令牌**（ContextVar），
模型传不进来，前端也传不进来。

**退出/换账号**：本项目在退出时清空前端会话显示并重新生成 `threadId`，
令牌失效后所有请求 401。因为后端不存历史，所以不存在"换账号后读到上一个人的对话"的问题；
如果将来做服务端历史，必须按 user_id 隔离查询，不能只靠 threadId。

---

## 9. 今天实际使用的版本

后端（`intern-day-2-backend`）：

| 包 | 版本 |
| --- | --- |
| Python | 3.13.14 |
| agent-framework-core | 1.26.0 |
| agent-framework-ag-ui | 1.8.1 |
| agent-framework-openai | 1.18.2 |
| fastapi | 0.162.2 |
| uvicorn | 0.54.0 |

前端（`intern-day-2-frontend`）：

| 包 | 版本 |
| --- | --- |
| @copilotkit/react-core | 1.90.2（用 `/v2` 子路径） |
| @copilotkit/react-ui | 1.90.2（用 `/v2` 子路径） |
| @copilotkit/runtime | 1.90.2（用 `/v2` 和 `/v2/express`） |
| @ag-ui/client | 1.0.5 |
| react | 19.3.1 |
| vite | 8.3.8 |
| typescript | 7.0.2 |

依赖锁文件：后端 `uv.lock`，前端 `pnpm-lock.yaml`，都已提交。

---

## 10. 参考链接

- [microsoft/agent-framework](https://github.com/microsoft/agent-framework)
- [Microsoft Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [AG-UI Integration with Agent Framework](https://learn.microsoft.com/en-us/agent-framework/integrations/ag-ui/)
- [Python AG-UI README](https://github.com/microsoft/agent-framework/blob/main/python/packages/ag-ui/README.md)
- [CopilotKit Docs](https://docs.copilotkit.ai/)
- [CopilotKit Architecture](https://docs.copilotkit.ai/concepts/architecture)
- [AG-UI Overview](https://docs.ag-ui.com/introduction)

---

## 11. 阅读后仍不理解的问题

1. **AG-UI 的 `state` 到底该放什么？**
   现在 `state` 传的是空对象。我能看懂它是"运行期可变的共享状态"，
   但不清楚它和 `forwardedProps` 的边界在哪，以及什么样的 UI 场景真的需要它。
   想找一个用了 state 的官方例子对着读。

2. **快照存储（`snapshot_store` / `AGUIThreadSnapshotStore`）和"我们要不要自己做历史持久化"的关系。**
   适配包里已经有快照机制，如果启用它，是不是就不用自己写会话历史表了？
   它的存储后端、清理策略、和登录用户的绑定方式我还没弄明白。

3. **`authorization_scope_resolver` 的返回值具体影响什么。**
   我按 `ag-ui:user:{id}` 返回，能跑通，但我不确定这个 scope 是被用来
   隔离快照、隔离 detached run、还是两者都有。需要读适配包源码确认。

---

## 12. 一个通过自己调试才弄懂的细节

**现象**：我一开始以为"鉴权失败"和"模型失败"是同一种错误，
前端只要判断 HTTP 状态码就行。

**怎么发现的**：我用一个**占位假 key** 起后端，然后 curl 打 `/agent`：

- 不带令牌 → `HTTP 401` + `{"detail":"登录状态无效，请重新登录"}` ✅ 符合预期
- 带伪造令牌 → `HTTP 401` ✅ 符合预期
- 带**合法令牌** → **`HTTP 200`**，然后流里出现
  `data: {"type":"RUN_ERROR","message":"...","code":"ChatClientException"}`

后端日志里能看到底层真实原因：DeepSeek 返回
`401 Authentication Fails, Your api key: ****heck is invalid`。

**弄懂了什么**：AG-UI 端点的设计是"**一旦开始输出事件流，就用事件报告错误**"，
不再改 HTTP 状态码。因为响应头早就发出去了，改不了。
所以前端的错误处理必须**两条路都覆盖**：

- 请求阶段失败 → 看 HTTP 状态码（401 要提示重新登录）
- 事件流阶段失败 → 看 `RUN_ERROR` 事件（要结束 loading，提示重试）

我原来只在 fetch 的 catch 里处理错误，那样模型 key 错了页面会**永远转圈**。
这个坑只有真的把假 key 打进去、看 SSE 原始输出才能发现——
本机跑单元测试是发现不了的，因为测试里没有真模型。

**顺带确认的**：这个实验也证明了鉴权是**真的在模型调用之前**拦截的。
如果是先调模型再校验，假 key 应该报模型错误而不是 401。实测是 401，说明顺序正确。

---

## 13. Mock 与真实模型的边界（如实标注）

| 验证项 | 状态 |
| --- | --- |
| `/agent` 端点注册 | ✅ 实测（占位 key 下 openapi 里能看到 `/agent`） |
| 未登录 401 拦截 | ✅ 实测 |
| 伪造令牌 401 拦截 | ✅ 实测 |
| SSE 事件流返回 `RUN_STARTED` / `RUN_ERROR` | ✅ 实测 |
| 真实模型对话 | ⬜ 取决于是否已配置有效 `MODEL_API_KEY`（见 README 的验证记录） |
| 工具调用真实执行 | ⬜ 同上，需在有额度环境下验证后回填 |

未验证的项目在 README 里同样标注，不写成"已通过"。
