# 第三天复盘：最难理解的概念、定位过的问题、怎么确认的

> 任务说明第九节要求「一段简短复盘：最难理解的一个概念、定位过的一个问题、自己是如何确认原因的」。
> 这里按真实发生的过程写，不美化。

---

## 一、最难理解的概念：AG-UI 是「协议」还是「传输」

**一开始的误解**：我以为 AG-UI 是一个能跑的东西——装上它，前端就能和后端说话。

**卡住的地方**：我在读文档时反复看到 `SSE`、`text/event-stream`、`WebSocket`
混在一起出现，分不清哪个是 AG-UI、哪个是 HTTP。任务说明还特意写了
「不要把 SSE 描述成 WebSocket」，说明这是个常见错误。

**怎么想通的**：用一次真实的 curl 请求把它拆开看。

```bash
curl -X POST http://localhost:8000/agent \
  -H "Authorization: Bearer <token>" \
  -d '{"threadId":"t1","runId":"r1","messages":[...]}'
```

返回是：

```
HTTP 200
data: {"type":"RUN_STARTED","threadId":"t1","runId":"r1"}

data: {"type":"TEXT_MESSAGE_CONTENT","delta":"2026-11 ..."}
```

这三层一下就分开了：

| 层 | 这次请求里具体是什么 | 作用 |
| --- | --- | --- |
| HTTP | `POST /agent`、`200`、`Authorization` 头 | 建立连接、传凭证 |
| SSE | `data: {...}` 分帧、不结束的响应体 | 怎么把数据一段段推下来 |
| AG-UI | `RUN_STARTED` / `TEXT_MESSAGE_CONTENT` 这些 `type` | 每段数据表示「发生了什么」 |

**结论**：AG-UI 规定「说什么」，SSE 规定「怎么送」，HTTP 规定「怎么连」。
它们是堆叠关系，不是替代关系。全程没有 WebSocket——没有 upgrade 握手，
就是一次普通 POST，响应没结束而已。

这个概念想通之后，第 4 问（消息经过哪些组件）和第 6 问（流式怎么显示）就都顺了。

---

## 二、定位过的问题：容器里调 Agent 一直 401，但同一令牌在宿主机上正常

这是今天花时间最久的问题，也是最有价值的一个。

### 现象

浏览器里点发送，Agent 面板一直转圈，最后报「助手暂时无法回复」。
但**页面本身的记账功能完全正常**——`/ledger/entries`、`/ledger/summary` 都是 200。

Runtime 日志：

```
Agent execution failed: Error: HTTP 401: {"detail":"登录状态无效，请重新登录"}
```

后端日志里**根本没有 `/agent` 的请求记录**，只有 `/health` 和 `/auth/login`。

### 第一步：先确认令牌本身没问题

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login ... | jq -r .token)
curl -X POST http://localhost:8000/agent -H "Authorization: Bearer $TOKEN" ...
# → HTTP 200，正常返回 RUN_STARTED
```

宿主机上用同一个令牌是通的，所以**问题不在令牌，也不在后端鉴权逻辑**。

### 第二步：怀疑 Runtime 没把 header 传下去

我在 `runtime.mjs` 的 `agents` 回调里临时加了一行日志：

```js
console.log('[runtime] agents() auth =', authorization ? 'Bearer len=' + authorization.length : 'NONE')
```

输出：

```
[runtime] agents() auth = Bearer len=50 -> target http://host.docker.internal:8000/agent
```

`len=50` = `"Bearer "` (7) + 43 位令牌，**说明 Runtime 确实拿到了正确的 header**，
也正确构造了 `HttpAgent`。所以问题不在 Runtime 的取值逻辑。

### 第三步：关键的对照实验

既然 Runtime 拿到了正确 header，那就在**容器里**直接发一个请求，绕开所有业务代码：

```bash
# 从 runtime 容器 → 宿主机地址
node -e "fetch('http://host.docker.internal:8000/auth/me',{headers:{Authorization:'Bearer '+TOKEN}})"
# → HTTP 401

# 从宿主机 → 同一个后端
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/auth/me
# → HTTP 200
```

**同一个令牌、同一个后端、同一个接口，只有网络路径不同，结果一个 200 一个 401。**

### 第四步：换一个地址验证假设

```bash
# 拿到容器看到的网关地址
ip route | awk '/default/ {print $3}'   # → 172.19.0.1

# 用网关 IP 而不是 host.docker.internal
node -e "fetch('http://172.19.0.1:8000/auth/me',{headers:{Authorization:'Bearer '+TOKEN}})"
# → HTTP 200 {"id":1,"username":"demo",...}
```

**确认了**：`host.docker.internal` 这条路径会丢失 Authorization 头。

### 根因与修复

这台 Windows 机器上，容器经 `host.docker.internal` 访问宿主机时，
请求会被本机代理接管，`Authorization` 头在转发过程中丢失。
后端收到一个没有凭证的请求，自然返回 401——**这不是我们的代码 bug，是环境差异**。

修复方式不是绕过它，而是换一个更正确的拓扑：两个 Compose 项目通过
**显式共享网络**对接，运行时用服务名 `api` 直连，不经宿主机端口：

```yaml
# 两个仓库都加入这个外部网络
networks:
  shared:
    name: intern-day-shared
    external: true
```

```yaml
# 后端给它起别名 api
shared:
  aliases: [api]
```

```yaml
# Runtime 直连服务名
BACKEND_AGENT_URL: http://api:8000/agent
```

改完后 `GET /auth/me` 和 `POST /agent` 都恢复正常。

### 这个问题的价值

1. **它证明「前端隐藏入口」不等于安全**：真正拦住未授权的是后端的 401，
   而这次 401 是在网络层就把凭证弄丢了，说明凭证传递路径必须逐段验证。
2. **任务说明特意强调「不能假定对方服务名天然可解析」**，我一开始正是按
   「用 host.docker.internal 就行」的做法写的，结果踩了坑。改成共享网络后，
   既符合文档建议，也真的解决了问题。
3. **定位方法可复用**：不要一上来改代码，先做「同一输入、两种路径」的对照，
   能快速把问题圈定在网络层还是应用层。

---

## 三、另一个小问题：改过密码后登录一直失败

**现象**：改了 `.env` 里的 `SEED_PASSWORD`，重启容器后登录仍提示「账号或密码错误」。

**原因**：`seed.py` 只在账号**不存在**时创建用户：

```python
exists = db.scalar(select(User).where(User.username == settings.seed_username))
if exists is not None:
    return None   # 已存在就直接返回，不更新密码
```

而数据库在命名卷里，`docker compose down` 不会删数据，所以旧密码一直在。

**确认方法**：对比容器内环境变量与 `.env` 的哈希，发现不一致；
再读 `seed.py` 确认逻辑。

**解决**：`docker compose down -v` 清空卷后重建（会丢账目数据），
这个行为已写进 README 的「练习账号初始化」一节。

---

## 四、还没解决的

- **真实模型对话未完成**：本次的 `MODEL_API_KEY` 认证能通过（`/models` 返回 200），
  但账户余额为 0，调用返回 `Insufficient Balance`。流式、工具、多轮三项是用
  本地 Mock 模型验证的，验证的是协议与链路，不验证真实模型的语义能力。
  换有额度的密钥后需要复验并回填 README。
- **`state` 与 `forwardedProps` 的边界**：目前 `state` 传空对象，能跑通，
  但我不确定什么样的 UI 场景真的需要它。想找一个用了 `state` 的官方例子对照读。
- **`authorization_scope_resolver` 的返回值影响范围**：我返回
  `ag-ui:user:{id}` 能跑通，但不清楚这个 scope 到底隔离了快照、detached run，
  还是两者都有。需要读适配包源码确认。
