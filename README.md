# 雪庐记账 · 后端（intern-day-2-backend）

登录鉴权 + 个人记账接口。Python + FastAPI，数据落 SQLite，容器启动时自动建表并创建练习账号。

## 功能范围

**必做**：健康检查、账号密码登录、获取当前用户、退出登录，四个接口都由后端真实校验。

**自选功能**：个人记账。按月新增、查询、删除账目，并返回月度收支汇总；所有账目接口都校验登录状态，并且只能操作本人的数据。

**不包含**（按任务说明不做）：注册、找回密码、短信/第三方登录、角色权限。

### 验收条件

- 错误账号与错误密码返回同一句提示，不泄露账号是否存在。
- 未携带、伪造、已过期、已退出的令牌访问受保护接口一律 `401`。
- 接口响应与日志中不出现密码或完整令牌；密码只存 bcrypt 哈希，会话表只存令牌摘要。
- 同一账号看不到、删不掉他人的账目。
- `docker compose up --build` 在仓库根目录即可独立启动，不依赖另一个仓库。

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI 0.163 + Uvicorn |
| 数据访问 | SQLAlchemy 2.1（ORM）+ SQLite |
| 密码 | bcrypt 5.0（直接调用，不经 passlib） |
| 依赖管理 | uv 0.13（`pyproject.toml` + `uv.lock`） |
| 配置 | 环境变量 / `.env`（python-dotenv 读取） |
| 容器 | Docker + Docker Compose（命名卷持久化） |

## 目录结构

```
app/
  main.py        应用入口：CORS、路由装配、启动时建表 + 建练习账号
  config.py      配置读取与校验（缺 SEED_PASSWORD 直接给出可操作提示）
  db.py          引擎、会话工厂、建表
  models.py      users / sessions / entries 三张表
  schemas.py     出入参定义（金额对外是元、落库是分；时间统一带 UTC 标记）
  security.py    bcrypt 哈希、不透明令牌、SHA-256 摘要
  deps.py        Bearer 令牌鉴权依赖
  routers/
    auth.py      /auth/login、/auth/me、/auth/logout
    ledger.py    /ledger/entries、/ledger/summary
tests/           接口回归用例（pytest，16 条）
Dockerfile       运行镜像：uv 按 uv.lock 安装依赖
compose.yaml     独立启动 + 命名卷
.devcontainer/   开发容器（git + uv）
```

## 快速开始（Docker Compose）

```bash
cp .env.example .env          # 必须：把 SEED_PASSWORD 改成自己的练习密码
docker compose config
docker compose up --build -d  # 首次构建约 1 分钟
docker compose ps             # 期待 api 状态为 Up (healthy)
docker compose logs --tail=100
```

服务地址：<http://localhost:8000>，交互式文档：<http://localhost:8000/docs>

> 没有 `.env` 时 Compose 不会直接失败（`env_file` 设为 `required: false`），但应用启动会打印
> 「缺少 SEED_PASSWORD 环境变量」并退出，不会带着空密码跑起来。

### 冒烟验证

```bash
curl -s http://localhost:8000/health

# 登录（把 demo / 密码换成 .env 里的值）
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"你的密码"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/ledger/entries \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"kind":"income","amount":3000,"category":"工资","note":"虚构的月薪"}'

curl -s "http://localhost:8000/ledger/summary" -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/auth/logout -H "Authorization: Bearer $TOKEN"
```

## 练习账号初始化

> 改过 `SEED_PASSWORD` 之后如果登录一直提示「账号或密码错误」，先确认是不是**沿用旧数据卷**：种子账号只在账号不存在时创建，已存在不会更新密码。
> 需要按新密码重建时用 `docker compose down -v`（会清空账目数据）再 `up -d`；不想丢数据就在页面里换回旧密码，或直接改数据库里的 `password_hash`。

账号不是硬编码，而是启动时按环境变量创建（`app/seed.py`）：

1. `cp .env.example .env`；
2. 设置 `SEED_USERNAME`（默认 `demo`）与 `SEED_PASSWORD`（必填，否则服务拒绝启动）；
3. `docker compose up --build -d`，首次启动时若账号不存在则创建，日志打印 `[启动] 已创建练习账号 demo`；
4. 用该账号登录前端或直接调 `/auth/login`。

所有数据都是虚构的，仓库里没有真实密码。

## 与前端联调

前端仓库：<https://github.com/fan-beijing/intern-day-2-frontend>

两个仓库是独立的 Compose 项目，容器之间没有服务发现。**浏览器直连宿主机映射端口**：

- 前端：`http://localhost:5173`（由前端 `VITE_API_BASE_URL` 指向本服务）
- 后端：`http://localhost:8000`
- 因此 `.env` 的 `CORS_ORIGINS` 必须包含 `http://localhost:5173`；`CORSMiddleware` 已配置 `allow_credentials` 与全部方法与头部，预检请求按默认处理。

容器内的 `localhost`、Compose 服务名和浏览器可访问地址是三件不同的事，这里统一用宿主机端口联调。

## 接口清单

| 方法 | 路径 | 是否需登录 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 健康检查，容器 healthcheck 用 |
| POST | `/auth/login` | 否 | 账号密码登录，返回不透明令牌与过期时间 |
| GET | `/auth/me` | 是 | 返回当前用户，前端刷新页面时用它校验登录态 |
| POST | `/auth/logout` | 是 | 删除当前会话行，旧令牌立即失效 |
| POST | `/ledger/entries` | 是 | 新增收入 / 支出账目 |
| GET | `/ledger/entries?month=YYYY-MM` | 是 | 按月查看本人账目，默认当月 |
| DELETE | `/ledger/entries/{id}` | 是 | 删除本人账目 |
| GET | `/ledger/summary?month=YYYY-MM` | 是 | 月度收入 / 支出 / 结余 |
| POST | `/agent` | 是 | 第三天：AG-UI 事件流入口，见下文「Agent 对话」 |

完整字段与校验规则见 `/docs`（OpenAPI）。时间字段统一以 `UTC` 结尾输出，例如 `2026-11-15T14:40:23Z`。

### 关键设计

- **登录态**：`secrets.token_urlsafe(32)` 生成不透明令牌，明文只返回客户端一次；`sessions` 表只存
  SHA-256 摘要 + `user_id` + `expires_at`（默认 120 分钟）。库被读走也无法直接冒用令牌；退出即删行。
- **密码**：bcrypt（cost 12）哈希。`bcrypt 5.x` 对超过 72 字节的输入会抛异常，`security.py` 统一按字节截断。
- **错误口令**：账号不存在与密码错误返回同一句 `账号或密码错误`，且账号不存在时也跑一次 bcrypt，抹平响应时间差。
- **数据隔离**：账目查询一律带 `user_id`；删除他人记录返回 `404` 而非 `403`，不泄露记录是否存在。
- **金额**：存整数「分」，汇总时再换算成元，避免浮点累加误差。
- **过期清理**：命中过期会话时顺手删行，避免 `sessions` 表无限增长。
- **参数校验**：全部使用请求/响应模型；`month` 用正则约束为 `YYYY-MM`，非法值返回 `422`。

## 第三天：Agent 对话（Microsoft Agent Framework + AG-UI）

登录后的记账页多了一个「雪庐小账房」聊天面板。后端负责跑 Agent，前端只负责显示。

- 接口：`POST /agent`，返回 `text/event-stream`（AG-UI 事件流），**必须带登录令牌**。
- Agent：`xuelu-ledger-assistant`，名称、指令与能力边界写在 `app/routers/agent.py` 的 `AGENT_INSTRUCTIONS`。
- 只用了一个只读工具 `month_summary`：查询**当前登录用户**某个月的收支汇总，绝不写库。
- 身份来源：`verify_agent_login` 依赖校验 Bearer 后写入 `ContextVar`，工具执行时读取。
  模型只能决定 `month` 参数，无法指定 `user_id`；并发请求各持一份上下文，不会串号。

### 模型配置（只在后端）

| 变量 | 说明 | 示例（占位） |
| --- | --- | --- |
| `MODEL_API_KEY` | 模型服务密钥，未设置则 `/agent` 不注册 | `sk-...` |
| `MODEL_BASE_URL` | OpenAI 兼容服务地址，必须 https（本机 Mock 允许 http://127.0.0.1） | `https://api.deepseek.com/v1` |
| `MODEL_ID` | 模型名 | `deepseek-chat` |

密钥只写进本地 `.env`（已被 gitignore），不进镜像构建参数、不进代码、不进前端环境变量。

> 注意：DeepSeek 这类兼容服务只实现了 `/chat/completions`，不支持 OpenAI 新的 `/responses`。
> 所以这里用 `OpenAIChatCompletionClient`，不是 `OpenAIChatClient`（后者会 404）。

### 认证与失败路径

- 未登录 / 令牌过期：在**进入 Agent 之前**返回 `401`，不会产生任何模型调用（有测试覆盖）。
- 运行中出错：AG-UI 返回 `RUN_ERROR` 事件，前端结束 loading 并提示重试。
- 换账号或退出：前端清掉令牌并卸载聊天组件；旧令牌再请求 `/agent` 同样是 `401`。

### 会话行为

对话历史由浏览器持有，每次运行把当前会话消息一起发上来；后端不落库。
因此**刷新页面或重启服务后历史会丢失**，只有「当前这次会话」有效。`threadId`/`runId`
只用于标识会话与运行，不能当凭证使用。

### 无模型额度时：用 Mock 验证链路

`compose.mock.yaml` 提供一个**本地 Mock 模型服务**，用于在没有可用额度时
验证「流式事件 + 工具调用闭环 + 多轮上下文」。它是真实的 HTTP 服务：
真的按 SSE 逐块返回 `chat.completion.chunk`，真的返回 `tool_calls`，
Agent Framework 真的会去执行 `month_summary`、拿真实数据库结果、再请求一次。

```bash
docker compose -f compose.yaml -f compose.mock.yaml up -d --build
```

启动后 `api` 使用 `MODEL_BASE_URL=http://mock:8899/v1`、`MODEL_ID=mock-model`，
浏览器照常访问 5173，Agent 面板的回复来自 Mock。

**它不验证什么**：真实模型的语义理解与回答质量。
凡基于 Mock 的结论在本文与 PR 里都标注了 Mock，不写成「真实模型测试通过」。

### 版本与文档

- agent-framework-core 1.26.0 · agent-framework-ag-ui 1.8.1 · agent-framework-openai 1.18.2（见 `uv.lock`）
- 原理说明：[`docs/day-3-agent-learning.md`](docs/day-3-agent-learning.md)
- 交互图：[`docs/diagrams/day-3-agent-interaction.png`](docs/diagrams/day-3-agent-interaction.png)

### 第三天自测记录

分两类如实记录：**不依赖模型额度的链路项**已实测通过；**依赖真实模型调用**的项目
在配置有效 `MODEL_API_KEY` 后补充，未验证的不写成通过。

| 检查项 | 验证方式 | 结果 |
| --- | --- | --- |
| 端点注册 | 配置 `MODEL_API_KEY` 后读取 `GET /openapi.json` | ✅ `/agent` 出现在路径列表中 |
| 未登录访问 | 不带令牌直接 `POST /agent` | ✅ `401`，提示「登录状态无效，请重新登录」 |
| 伪造令牌 | `Authorization: Bearer <随机串>` 调 `/agent` | ✅ `401`，未进入模型调用 |
| 拒绝发生在模型之前 | 用占位 key（无效密钥）复现上述两种请求 | ✅ 先得到 `401`，说明鉴权早于任何模型调用 |
| AG-UI 事件流 | 合法令牌 + 占位 key 调 `/agent`，观察原始响应 | ✅ `HTTP 200`，先 `RUN_STARTED`，后 `RUN_ERROR`（`ChatClientException`） |
| 事件流是 SSE 而非 WebSocket | 检查响应体为 `data: {...}` 分帧、`text/event-stream` | ✅ 全程单个 HTTP POST，无 upgrade |
| 密钥不落前端 | 检查前端环境变量与构建产物 | ✅ 前端只有 `VITE_API_BASE_URL` 与 Runtime 地址，无 `MODEL_*` |
| 容器内端点注册 | 后端容器启动后读取容器内 `/openapi.json` | ✅ `/agent` 在路径列表中，容器能读到 `MODEL_ID=deepseek-chat` |
| 容器内鉴权拦截 | 在容器里重跑「无令牌 / 伪造令牌」两次请求 | ✅ 均 `401`，与宿主机结果一致 |
| 流式增量渲染 | 浏览器发送问题，观察消息逐字出现（非整段弹出） | ✅ Mock 链路下 `TEXT_MESSAGE_CONTENT` 分 11 次到达，页面逐步更新 |
| 多轮上下文 | 轮1「我叫阿雪」→ 轮2「我叫什么名字？」 | ✅ 轮2 正确复述「阿雪」，说明历史消息真的参与 |
| 只读工具真实执行 | 问「我11月花了多少钱」，与 `/ledger/summary` 对账 | ✅ `TOOL_CALL_*` 事件完整，工具查出 `支出 88.88 元、共 1 笔`，与页面汇总一致 |
| 工具不会被误触发 | 问「你好，我叫阿雪」这类非账目问题 | ✅ 不产生 `TOOL_CALL`，只有文本事件 |
| 新建对话 | 点击「新建对话」后再提问 | ✅ 换新 threadId，旧消息不再出现 |
| 真实模型流式回复 | 配置有效 `MODEL_API_KEY` 后发送问题 | ⬜ 账户余额为 0（`Insufficient Balance`），需充值或换有额度的密钥后复验 |

> 当前状态说明：**协议链路已全部实测通过**（鉴权、SSE 事件流、工具闭环、多轮上下文、
> 前端逐步渲染、容器编排）。上表里标注 ✅ 的流式/工具/多轮三项，是在
> `compose.mock.yaml` 提供的**本地 Mock 模型**下验证的——Mock 服务是真实的 HTTP 服务，
> 真的按 SSE 逐块返回、真的触发 `tool_calls`、工具真的查了数据库，验证的是协议与链路，
> **不验证真实模型的语义能力**。
>
> 本次使用的 `MODEL_API_KEY` 认证能通过（`/models` 返回 200），但账户余额为 0，
> 调用返回 `Insufficient Balance`，因此**真实模型对话未完成**，如实标注为未通过。
> 换用有额度的密钥后，把 `.env` 的 `MODEL_API_KEY` 换掉、去掉 `compose.mock.yaml`
> 重新 `up -d` 即可复验这一行。
>
> 关于「拒绝发生在模型之前」这条的取证方法：使用一个格式合法但无效的占位密钥
> 启动服务（端点会注册），不带令牌时得到 `401`；带合法令牌时才真正请求模型服务并拿到
> 上游的鉴权错误。两次结果不同，说明拦截点在模型调用之前。
> 这条日志里不含任何真实密钥。

## 开发

### A. VS Code 开发容器（推荐）

仓库带 `.devcontainer/`（Python 3.13 + git + uv）。打开本仓库后 `Dev Containers: Reopen in Container`，
容器会按 `devcontainer.json` 执行 `uv sync --frozen`，之后在容器终端里：

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run pytest
```

开发容器的命令级实测记录（`@devcontainers/cli` 构建、容器内工具版本、`uv sync --frozen`、16 条用例通过）见
[`docs/devcontainer-check.md`](docs/devcontainer-check.md)。

### B. 本机虚拟环境

```bash
# 需要先安装 uv：https://docs.astral.sh/uv/
uv sync --frozen
cp .env.example .env
export DATABASE_URL="sqlite:///$(pwd)/data/app.db"   # 本机跑时不要用容器内路径
uv run uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
uv run pytest          # 或 .venv/Scripts/python.exe -m pytest
```

16 条用例，覆盖登录链路、鉴权分支（无令牌 / 伪造 / 非 Bearer / 空令牌）、令牌过期、退出后旧令牌失效、
记账 CRUD 与汇总、越权删除、金额与月份参数校验。

## 数据保存

`compose.yaml` 把 `/app/data` 挂到命名卷 `intern-day-2-backend-data`：

- `docker compose down` **不丢**数据，重启后账目与用户仍在；
- 会话也存在同一个库里，所以重启后未过期的令牌依然有效；
- `docker compose down -v` 才会彻底清空，下次启动重新建表并重建练习账号。

## 自测记录

| 检查项 | 操作 | 实际结果 |
| --- | --- | --- |
| 开发容器 | 构建 `.devcontainer` 镜像，容器内执行 `uv sync --frozen`、`uv run pytest` | 依赖安装成功，16 项用例通过 |
| 容器启动 | `docker compose up --build -d` + `docker compose ps` | `Up (healthy)`，`/health` 返回 `{"status":"ok"}` |
| 健康检查 | `curl /health` | `200`，不需要登录 |
| 正常登录 | 正确账号密码 | `200`，返回令牌、过期时间与用户信息 |
| 无效登录 | 错误账号 / 错误密码 | 均 `401`，提示统一为「账号或密码错误」 |
| 参数校验 | 空账号、空对象、超长字段 | `422`，返回字段级错误 |
| 当前用户 | 携带令牌访问 `/auth/me` | `200`，只返回 id、username、created_at |
| 未授权访问 | 无令牌 / 伪造令牌 / `Basic` 头 | 均 `401` |
| 凭证过期 | 将会话 `expires_at` 改到过去 | `401`，且过期会话行被清理 |
| 退出登录 | 退出后再用旧令牌 | `401` |
| 自选功能 | 新增收入与支出、按月查询、删除 | 汇总与列表数值一致；删除他人记录 `404` |
| 重启验证 | `docker compose down` 后再 `up -d` | 服务恢复，账目数据保留 |

自动化结果：`pytest` 16 项全部通过；前端联调时用真实浏览器走完登录 → 记账 → 刷新 → 退出，接口全部按预期响应。

实际执行的命令与响应见 [`docs/verification.md`](docs/verification.md)，接口总览截图见
[`docs/screenshots/01-swagger.png`](docs/screenshots/01-swagger.png)。

## 已知取舍

- 用 SQLite 单文件，未引入独立数据库；并发写入压力不在一天练习范围内。
- 会话表没有定时清扫任务，只在命中过期会话时顺手删行；用户量小时足够。
- 前后端是两个独立 Compose 项目，容器之间没有服务发现，靠浏览器直连宿主机端口联调；
  生产环境更常见的是 Nginx 反向代理统一入口。
- 未做限流与登录失败次数限制，练习场景未引入。
