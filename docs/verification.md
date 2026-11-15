# 启动与接口验证记录

记录时间：2026-11-15，在 Windows + Docker Desktop 上按 README 的步骤实跑。
令牌只显示前 8 位，密码用占位符替代，避免把凭证写进仓库。

## 1. 容器启动

```text
$ docker compose config
（配置校验通过，无告警）

$ docker compose up --build -d
 Image intern-day-2-backend:local Built
 Volume intern-day-2-backend-data Created
 Container intern-day-2-backend Started

$ docker compose ps --format "table {{.Name}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
NAME                   IMAGE                        STATUS                   PORTS
intern-day-2-backend   intern-day-2-backend:local   Up 2 minutes (healthy)   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
```

`Up (healthy)` 来自 Dockerfile 的 HEALTHCHECK。

## 2. 健康检查（无需登录）

```text
$ curl -s http://localhost:8000/health
{"status":"ok"}
```

## 3. 登录

```text
$ curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"demo","password":"<.env 中的 SEED_PASSWORD>"}'
{"token":"LJ23Ht8v…","token_type":"bearer","expires_at":"2026-11-15T14:40:23Z",
 "user":{"id":1,"username":"demo","created_at":"2026-11-15T12:38:43Z"}}
```

时间字段带 `Z`，前端不会按本地时间误读。

## 4. 错误密码

```text
$ curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"demo","password":"wrong-password"}'
{"detail":"账号或密码错误"}          # 401

$ curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"nobody","password":"whatever"}'
{"detail":"账号或密码错误"}          # 401，与密码错误同一句提示
```

## 5. 当前用户

```text
$ curl -s http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
{"id":1,"username":"demo","created_at":"2026-11-15T12:38:43Z"}
```

## 6. 未携带 / 伪造令牌

```text
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/auth/me
401

$ curl -s -X POST http://localhost:8000/auth/logout -H "Authorization: Bearer forged-token-value"
{"detail":"登录状态无效，请重新登录"}   # 401
```

## 7. 记账与汇总

```text
$ curl -s -X POST http://localhost:8000/ledger/entries \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"kind":"income","amount":3000,"category":"工资","note":"虚构的月薪"}'
{"id":1,"kind":"income","amount":3000.0,"category":"工资","note":"虚构的月薪",
 "occurred_on":"2026-11-15","created_at":"2026-11-15T12:41:02Z"}          # 201

$ curl -s "http://localhost:8000/ledger/summary?month=2026-11" -H "Authorization: Bearer $TOKEN"
{"month":"2026-11","income":3000.0,"expense":38.5,"balance":2961.5,"count":2}
```

## 8. 退出后旧令牌失效

```text
$ curl -s -X POST http://localhost:8000/auth/logout -H "Authorization: Bearer $TOKEN"
{"detail":"已退出登录"}

$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
401

$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ledger/entries -H "Authorization: Bearer $TOKEN"
401
```

## 9. 自动化用例

```text
$ uv run pytest
................                                                         [100%]
16 passed
```

覆盖：健康检查、登录成功/失败、统一错误提示、参数校验、四种非法凭证、令牌过期与会话清理、
退出后旧令牌失效、记账 CRUD、月度汇总、越权删除、金额与月份参数校验。

## 10. 重启验证

```text
$ docker compose down            # 保留命名卷
$ docker compose up -d
$ curl -s http://localhost:8000/health
{"status":"ok"}
```

重新启动后账目数据仍在（数据落在命名卷 `intern-day-2-backend-data`）；
执行 `docker compose down -v` 才会清空并重建练习账号。
