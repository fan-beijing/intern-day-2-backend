# PR：后端 · 第三天 Agent Framework + AG-UI 接入

标题：`feat(backend): 增加 Agent Framework 与 AG-UI 接入`

---

## 目标

在第二天的登录鉴权与记账后端基础上，用 **Microsoft Agent Framework（Python）** 定义一个记账助手 Agent，
通过官方 **AG-UI** 适配层在 FastAPI 暴露受登录保护的 `POST /agent`，回复以 SSE 事件流输出。
登录、当前用户、退出、记账等原有能力全部保留。

配套前端仓库：<https://github.com/fan-beijing/intern-day-2-frontend>（分支 `feat/agent-chat`）

## 今日 Agent 主题与能力范围

- **主题**：记账助手「雪庐小账房」，嵌在登录后的记账页里。
- **能做什么**：回答通用记账问题；查询**当前登录用户**某月的收支汇总并据此作答。
- **不能做什么**：不增删改账目、不访问他人数据、不执行命令、不调用外部接口。
  指令里明确写了「涉及账目的数字必须来自工具返回值，绝不编造」。

## 只读工具

`month_summary(month: str | None = None)`：

- 从 SQLite 读取**当前登录用户**指定月份的收支汇总（收入 / 支出 / 结余 / 笔数），纯只读。
- 用户身份来自 `ContextVar`，由已通过 Bearer 校验的依赖写入；
  **模型只能决定 `month` 参数，无法指定 `user_id`**，前端也传不进来。
- 模型传了非法月份格式时返回提示文本，不抛异常。

## 主要改动

```
app/agent_config.py        模型服务配置（只从环境变量读，未配置则不注册端点）
app/agent_identity.py      请求级身份 ContextVar
app/routers/agent.py       Agent 定义、只读工具、AG-UI 端点注册
app/main.py                组装：有密钥才注册 /agent，未配置时降级并打印提示
compose.yaml               透传 MODEL_* 变量；加入共享网络并起别名 api
compose.mock.yaml          可选：本地 Mock 模型服务，用于无额度时验证链路
scripts/mock_model_server.py  Mock 模型服务（OpenAI 兼容，真 SSE + 真 tool_calls）
pyproject.toml / uv.lock   引入 agent-framework-ag-ui / agent-framework-openai
docs/day-3-agent-learning.md   原理说明（8 个问题逐条回答）
docs/day-3-retrospective.md    复盘（含一个问题的完整定位过程）
docs/day-3-demo-script.md      5—8 分钟演示脚本
docs/diagrams/day-3-agent-interaction.png  自绘交互图
```

## 实际 SDK 版本

| 包 | 版本 |
| --- | --- |
| Python | 3.13.14 |
| agent-framework-core | 1.26.0 |
| agent-framework-ag-ui | 1.8.1 |
| agent-framework-openai | 1.18.2 |
| fastapi | 0.162.2 |
| uvicorn | 0.54.0 |

依赖锁文件 `uv.lock` 已提交。

> 用 `OpenAIChatCompletionClient` 而不是 `OpenAIChatClient`：DeepSeek 这类 OpenAI 兼容服务
> 只实现 `/chat/completions`，不支持 `/responses`，用后者会 404。

## Runtime 拓扑

```
浏览器(localhost:5173)
  → Vite 同源代理 /api/copilotkit
  → CopilotKit Runtime(runtime:4000，在另一个 Compose 项目)
  → 共享网络 intern-day-shared 中的服务名 api:8000
  → FastAPI POST /agent（AG-UI，SSE）
  → Agent Framework → 模型服务 / 只读工具 → SQLite
```

两个仓库是独立 Compose 项目，**用显式共享网络对接**，不依赖 `host.docker.internal`
（该路径在 Win + Docker Desktop 上会丢失 Authorization，详见「已知问题」）。

## 所需环境变量（只写占位值）

| 变量 | 说明 | 占位示例 |
| --- | --- | --- |
| `SEED_USERNAME` | 练习账号 | `demo` |
| `SEED_PASSWORD` | 练习账号密码 | `change-me` |
| `MODEL_API_KEY` | 模型服务密钥，**未设置则 `/agent` 不注册** | `sk-...` |
| `MODEL_BASE_URL` | OpenAI 兼容地址，必须 https | `https://api.deepseek.com/v1` |
| `MODEL_ID` | 模型名 | `deepseek-chat` |
| `DATABASE_URL` | 数据库 | `sqlite:////app/data/app.db` |

`.env.example` 只有占位值；`.env` 在 `.gitignore` 与 `.dockerignore` 中。
密钥不进镜像构建参数、不进前端环境变量、不进代码。

## 验证记录

### 协议链路（Mock 模型，已通过）

后端用 `compose.mock.yaml` 起本地 Mock 模型（真 SSE + 真 `tool_calls`），
浏览器端到端跑通，事件序列来自真实响应：

| 检查项 | 结果 |
| --- | --- |
| 未登录调 `/agent` | `401`，且**模型未被调用**（拒绝发生在 Agent 之前） |
| 伪造令牌调 `/agent` | `401` |
| 合法令牌 + Mock | `200`，事件：`RUN_STARTED` → `TOOL_CALL_START/ARGS/END/RESULT` → `TEXT_MESSAGE_START/CONTENT×11/END` → `RUN_FINISHED` |
| 流式增量 | `TEXT_MESSAGE_CONTENT` 分 11 次到达，页面逐步更新 |
| 工具真实执行 | 工具返回「2026-11 汇总：支出 88.88 元，共 1 笔」，与 `/ledger/summary` 一致 |
| 工具不误触发 | 问「你好，我叫阿雪」不产生 `TOOL_CALL` |
| 多轮上下文 | 轮1「我叫阿雪」→ 轮2「我叫什么名字？」正确复述「阿雪」 |
| 传输方式 | 单个 HTTP POST，`text/event-stream`，无 WebSocket upgrade |

### 容器

| 检查项 | 结果 |
| --- | --- |
| 两个 Compose 项目各自构建启动 | 后端 `Up (healthy)`，前端 web + runtime 均正常 |
| 跨项目连通 | Runtime 经共享网络访问 `api:8000`，`/health` 与 `/auth/me` 均 200 |
| 从零复现 | 清空卷与网络后按 README 步骤重建，登录 → 对话 → 工具调用全部可复现 |

### 真实模型（已通过）

密钥由导师提供，走阿里云百炼的 OpenAI 兼容接口：

```ini
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_ID=deepseek-v4.1-flash
```

| 检查项 | 结果 |
| --- | --- |
| 真实模型流式回复 | ✅ 逐字返回，`TEXT_MESSAGE_CONTENT` 多块到达 |
| 真实模型触发只读工具 | ✅ 问「本月花了多少」，模型调 `month_summary`，返回「支出 180.30 元，共 2 笔」，与 `/ledger/summary` 完全一致 |
| 账目为空时不编造 | ✅ 同一个问题，账目为空时回答「本月还没有任何账目记录」 |
| 真实模型多轮上下文 | ✅ 轮1「我叫阿雪，爱吃火锅」→ 轮2 准确复述，并说明只在本对话内记住 |
| 鉴权仍在模型之前 | ✅ 未登录 401，零模型调用 |

上表中 Mock 相关项保留记录：`compose.mock.yaml` 用于无额度时验证协议链路，
文档里标注 Mock 的结论只证明链路通，不代表模型能力。

## 原理说明与交互图

- 原理说明：[`docs/day-3-agent-learning.md`](docs/day-3-agent-learning.md)
- 交互图（自绘）：[`docs/diagrams/day-3-agent-interaction.png`](docs/diagrams/day-3-agent-interaction.png)
- 复盘：[`docs/day-3-retrospective.md`](docs/day-3-retrospective.md)
- 演示脚本：[`docs/day-3-demo-script.md`](docs/day-3-demo-script.md)

前端 README 链接到本篇文档，两个仓库不重复维护两个版本。

## 已知问题与未完成项

1. **真实模型已接通**（阿里云百炼 `deepseek-v4.1-flash`）。换其他服务商时改
   `MODEL_BASE_URL` / `MODEL_ID` / `MODEL_API_KEY` 三个变量即可，代码不用动。
2. **`host.docker.internal` 丢失 Authorization**：本机 Windows + Docker Desktop 环境下，
   容器经该地址访问宿主机时 `Authorization` 头被本机代理改写丢失
   （同一令牌走它得 401，走 Docker 网关 `172.19.0.1` 得 200）。
   已改为共享网络直连服务名，README 写明 `docker network create intern-day-shared` 步骤。
3. **会话历史不落库**：历史存在浏览器，刷新页面即丢失；服务重启后同样不保留。
   这是今天明确的取舍，README 已写清。
4. **未做的**：多 Agent、RAG、向量库、MCP、审批流、生产部署，均不在今日范围。

## 敏感信息检查

- 截图、日志、文档中无真实密钥与完整令牌。
- `git ls-files` 核对过清单，`.env`、`data/`、`.venv/`、`__pycache__/` 均被排除。
- 演示用的占位密钥与真实密钥均未进入任何提交。
