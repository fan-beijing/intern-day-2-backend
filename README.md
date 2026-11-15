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

账号不是硬编码，而是启动时按环境变量创建（`app/seed.py`）：

1. `cp .env.example .env`；
2. 设置 `SEED_USERNAME`（默认 `demo`）与 `SEED_PASSWORD`（必填，否则服务拒绝启动）；
3. `docker compose up --build -d`，首次启动时若账号不存在则创建，日志打印 `[启动] 已创建练习账号 demo`；
4. 用该账号登录前端或直接调 `/auth/login`。

所有数据都是虚构的，仓库里没有真实密码。

## 与前端联调

前端仓库：<https://github.com/你的GitHub用户名/intern-day-2-frontend>（创建仓库后替换此处地址）

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

## 开发

### A. VS Code 开发容器（推荐）

仓库带 `.devcontainer/`（Python 3.13 + git + uv）。打开本仓库后 `Dev Containers: Reopen in Container`，
容器会按 `devcontainer.json` 执行 `uv sync --frozen`，之后在容器终端里：

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run pytest
```

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
