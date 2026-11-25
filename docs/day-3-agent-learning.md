# 第三天学习记录：Agent Framework、CopilotKit 与 AG-UI

> 这份文档记录我理解到的三层职责、一次完整交互的路径，以及实际踩到的问题。
> 实际版本：agent-framework-core 1.26.0 / agent-framework-ag-ui 1.8.1 / agent-framework-openai 1.18.2 /
> CopilotKit 1.90.2（@copilotkit/react-core、react-ui、runtime 同版本）/ FastAPI 0.162.2 / Python 3.13.14。
>
> 写完后的自查：下面每一段都应该能不看文档讲出来。凡是只能背名词的地方，说明还没真的懂。

## 1. Microsoft Agent Framework 解决什么问题

它解决的是「模型不会自己记事、不会自己查数据、也不会自己决定什么时候停」这三件事的组织问题。

在我这个项目里，一个 Agent 就是三样东西的组合：

- **模型客户端**（`OpenAIChatCompletionClient`）：负责真正发请求给模型服务，把流式返回的增量翻成统一的更新对象。
- **指令**（`instructions`）：一段固定的系统提示，规定身份（雪庐小账房）、能力边界（只能查汇总、不能改账）和回答风格。
- **工具**（`tools=[month_summary]`）：一个普通 Python 函数，被 `@tool` 装饰后带上名字、说明和参数 schema，模型能看见它、但不能直接执行它。

三者的关系是**循环**，不是一条直线：模型看到用户消息和工具清单，决定「我需要调用 month_summary(month="2026-11")」，框架负责真的执行这个函数，把返回值作为一条 tool 消息塞回上下文，再请模型继续生成。模型只做决策，执行永远在框架这一侧——这也是为什么"工具执行成功"这句话不能写死在提示词里，它必须是模型看到结果之后自己说出来的。

我为什么选 Python 版：第二天的后端就是 FastAPI，Agent 和只读工具都要访问同一个 SQLite 会话，放在同一个进程里最省事。

## 2. CopilotKit 在 React 里做什么

它把「聊天」这件事里跟业务无关的部分都包掉了：消息列表状态、流式增量如何合并、运行中的 loading、错误展示、工具调用卡片、会话切换。

我自己手写一个输入框的话，至少要自己实现：

1. 往哪个地址发、发什么格式（不是普通 JSON，是 AG-UI 的 run 请求）；
2. 收到 `text/event-stream` 后怎么按行切事件、怎么把 `TEXT_MESSAGE_CONTENT` 的增量拼成一条消息；
3. 运行开始/结束/失败三种状态怎么映射到 UI；
4. 工具调用开始和结果怎么显示，避免用户看到半截回答；
5. 会话（thread）切换、清空、退出时的清理。

CopilotKit 把这些变成了 `<CopilotKitProvider>` + `<CopilotChat>` 两个组件加几个 props。代价是要跟着它的版本走：1.90 里 v1 的 `CopilotRuntime` + `copilotRuntimeNodeExpressEndpoint` 已被标记为 deprecated，官方推荐 v2 的 `CopilotRuntime` + `createCopilotExpressHandler`，我用的是后者。

## 3. AG-UI 是什么，和 JSON 接口 / HTTP / SSE 的关系

AG-UI 是**事件协议**：它规定一次 Agent 运行过程中，服务端应该按什么顺序、用什么字段名，把「运行开始了」「文本又多了几个字」「模型要调工具了」「工具返回了」「运行结束了/失败了」这些事告诉前端。

它和传输方式的关系，我一开始是混在一起的，后来分清了：

| 层次 | 是什么 | 本项目里具体是 |
| --- | --- | --- |
| 协议 | 事件的名字、顺序、字段 | AG-UI：`RUN_STARTED`、`TEXT_MESSAGE_CONTENT`、`TOOL_CALL_*`、`RUN_FINISHED`、`RUN_ERROR` |
| 传输 | 这些事件怎么从服务器到浏览器 | HTTP POST + `text/event-stream`（SSE），服务端单向推送 |
| 和普通 JSON 接口的区别 | 普通接口一次请求一次响应；AG-UI 是一次请求、多次事件 | `POST /agent` 返回的不是一个 JSON body，而是一串 `data: {...}` |

**SSE 不是 WebSocket**：SSE 是单向的（服务端→浏览器）、基于普通 HTTP、断线可自动重连；WebSocket 是双向的、需要协议升级。这个项目里浏览器只发一次请求，之后全是服务端往回推，所以 SSE 足够，也不需要双向通道。

## 4. 从点击发送到看见回复，经过哪些组件

以「11 月花了多少」为例，逐段说清楚谁收到什么、返回什么：

1. **CopilotChat（浏览器）**：收到用户输入，把当前会话消息打包成一次 run 请求。
2. **CopilotKitProvider**：给请求加上 `Authorization: Bearer <登录令牌>`（headers 是个函数，每次请求现取），POST 到同源 `/api/copilotkit`。
3. **Vite（5173）**：把 `/api/copilotkit` 代理到 `runtime:4000`，浏览器不需要知道 Runtime 的真实端口，也就没有跨域预检。
4. **CopilotKit Runtime（4000）**：先检查有没有 Bearer，没有直接 401；有就用**这个请求自己的** Authorization 造一个 `HttpAgent`，把 AG-UI 请求转给 `http://host.docker.internal:8000/agent`。
5. **FastAPI 的依赖**：`verify_agent_login` 解析令牌，拿到 `user.id` 写进 `ContextVar` 和 `request.state`；失败就在这里 401，请求根本进不到 Agent。
6. **AG-UI 适配层**（`add_agent_framework_fastapi_endpoint`）：把 AG-UI 的 run 输入翻成 Agent Framework 的调用，并把返回的更新流翻回 AG-UI 事件。
7. **Agent**：带上指令、工具清单和消息历史请求模型。
8. **DeepSeek**：返回 `tool_calls`（要查 month_summary）。
9. **工具**：从 `ContextVar` 取当前用户 id（模型无法指定），查 SQLite，返回一段汇总文本。
10. **Agent**：把工具结果作为工具消息再请求模型，模型生成最终中文回答，过程中不断产出文本增量。
11. **AG-UI**：把增量转成 `TEXT_MESSAGE_CONTENT` 事件，经 Runtime 回给浏览器。
12. **CopilotChat**：按事件逐段追加渲染，`RUN_FINISHED` 后结束 loading。

## 5. Runtime 部署在哪、做什么，Vite 为什么不能顶替它

Runtime 是前端仓库里的一个独立 Node 服务（`server/runtime.mjs`，Express），在 Compose 里是第二个服务 `runtime`，容器内 4000，宿主机映射 4000。

它做三件事：把浏览器的运行请求转成对 Python `/agent` 的 AG-UI 请求；把 Python 回来的事件流原样转回浏览器；在转发前先做一次「有没有令牌」的粗筛。

Vite **不能**当 Runtime，原因是它根本不是应用服务器：它只做静态资源服务、模块转换和 HMR，没有 CopilotKit 的运行时逻辑，也不会替你实现 `POST /api/copilotkit` 的那套信封协议。我在 `vite.config.ts` 里写的只是 `proxy`——把请求转给真正的 Runtime，Vite 自身没有处理任何 Agent 逻辑。

## 6. 流式回复是怎么一点点显示出来的

关键在三个层次同时成立：

1. 模型服务按 token 流式返回（OpenAI 兼容接口的 `stream: true`）。
2. Agent Framework 把每个增量包装成更新对象，AG-UI 适配层再映射成 `TEXT_MESSAGE_CONTENT` 事件，逐条写进 SSE。
3. 前端每收到一条就追加到当前消息，不等整段结束。

前端如何识别一次运行的边界：`RUN_STARTED` 表示开始（清 loading、准备新消息），`TEXT_MESSAGE_CONTENT` 是增量，`RUN_FINISHED` 表示正常结束（停止 loading、允许再次发送）；中途出错是 `RUN_ERROR`，前端必须把它当成「这次运行结束」来处理，否则会一直转圈。

我实际验证时抓到的顺序是：
`RUN_STARTED → TEXT_MESSAGE_START → TOOL_CALL_START → TOOL_CALL_ARGS → TOOL_CALL_END → TOOL_CALL_RESULT → TEXT_MESSAGE_END → TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT ×N → TEXT_MESSAGE_END → MESSAGES_SNAPSHOT → RUN_FINISHED`。
注意中间出现了两次 `TEXT_MESSAGE_START/END`：一次是工具调用那一轮，一次是最终回答那一轮——这也是「工具真的被调用了」的证据。

## 7. 登录凭证和模型密钥分别归谁

| 凭证 | 谁产生 | 存在哪 | 发给谁 |
| --- | --- | --- | --- |
| 登录令牌 | 后端 `/auth/login` | 浏览器 localStorage | 每个请求的 `Authorization` 头 → Runtime 原样转发 → FastAPI 校验 |
| 模型 API Key | 导师提供 | 只有后端 `.env` / 容器环境变量 | 只有后端 → 模型服务 |

模型密钥绝对不能进浏览器，原因不是"怕被看到"这么简单：浏览器里的一切（环境变量、打包产物、Network 面板）用户都能拿到；一旦密钥进了前端，任何打开开发者工具的人都能用公司的额度，而且没法按用户审计。所以模型调用必须由后端发起，前端只知道「有个 Agent 在回答」。

同样地，Runtime 也不能替所有用户用一个管理员凭证去调后端——那样后端就无法区分谁是谁，越权隔离全部失效。我这里的做法是：Runtime 按请求取该请求的 Authorization，不缓存、不合并。

## 8. 对话上下文从哪来，threadId 和登录会话有什么区别

- **对话上下文**：由浏览器持有。每次运行，CopilotKit 把当前会话的历史消息一起发上来；后端不落库，所以刷新页面、服务重启后历史就没了（这一点写在 README 的「会话行为」里）。
- **threadId / runId**：AG-UI 用来标识「这是哪个会话的第几次运行」，用于事件归属和（可选的）服务端快照。它们是**标识符，不是凭证**——知道别人的 threadId 不代表能读别人的对话，因为真正的边界是 Authorization 对应的用户。
- **登录会话**：后端 `sessions` 表里的令牌记录，带过期时间。它决定「你是谁」，threadId 只决定「这是哪段对话」。

退出或换账号时：前端清掉 localStorage 的令牌、卸载聊天组件（历史自然消失）；旧令牌再请求 `/agent` 会被 401。服务端如果以后要存历史，必须按登录用户隔离，不能只凭 threadId 取。

## 9. 实际版本与参考链接

| 组件 | 版本 | 依据 |
| --- | --- | --- |
| Python | 3.13.14 | `python --version` |
| agent-framework-core | 1.26.0 | `uv.lock` |
| agent-framework-ag-ui | 1.8.1 | 固定版本，见 `pyproject.toml` |
| agent-framework-openai | 1.18.2 | `uv.lock` |
| CopilotKit（react-core / react-ui / runtime） | 1.90.2 | `pnpm-lock.yaml` |
| FastAPI | 0.162.2 | 与 agent-framework-ag-ui 的依赖约束兼容 |

- Microsoft Agent Framework 总览：<https://learn.microsoft.com/en-us/agent-framework/overview/>
- AG-UI 集成说明：<https://learn.microsoft.com/en-us/agent-framework/integrations/ag-ui/>
- Python AG-UI 包 README：<https://github.com/microsoft/agent-framework/blob/main/python/packages/ag-ui/README.md>
- CopilotKit 架构：<https://docs.copilotkit.ai/concepts/architecture>
- AG-UI 协议：<https://docs.ag-ui.com/introduction>

## 10. 还没完全弄懂的问题

1. `authorization_scope_resolver` 的返回值除了隔离审批状态，是否还影响服务端会话快照的键？我只验证了「不同用户之间不会串」，没有验证它在并发下的具体行为。
2. CopilotKit 的 `identifyUser` 我目前用「令牌摘要」当身份，这在多标签页共用同一令牌时是同一个身份；如果以后要按真实用户 id 隔离，是否应该让 Runtime 反查一次 `/auth/me`？代价是每个请求多一跳。
3. 模型侧的多轮上下文完全依赖浏览器每次重发历史，长对话会不会撞到上下文上限？框架里的 `compaction_strategy` 我没实际用过。

## 11. 一个自己调出来的细节

**症状**：后端能启动、`/agent` 也注册了，但一发消息就是 `RUN_ERROR`，日志里是 `ChatClientException ... Error code: 404`。

**定位**：把假模型服务的访问日志打开，看到它收到的是 `POST /v1/responses`——不是我以为的 `/v1/chat/completions`。查 `agent_framework_openai` 的源码才发现，`OpenAIChatClient` 默认走 OpenAI 新的 Responses API，而 DeepSeek 这类兼容服务只实现了 chat completions。

**修复**：换成 `OpenAIChatCompletionClient`（同一个包的另一个类），它请求 `/v1/chat/completions`。

**收获**：「OpenAI 兼容」这四个字不等于「兼容 OpenAI 的所有端点」。以后接任何兼容服务，先看它实际收到什么路径，比读文档快。
