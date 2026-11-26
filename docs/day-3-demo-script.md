# 第三天演示脚本（5—8 分钟）

> 目标：讲清「谁负责什么、消息怎么流、怎么验证成功」。
> 每一步都给一句「我为什么这样做」，避免只点页面不说话。

---

## 演示前 2 分钟准备（不进演示时间）

```bash
# 1) 共享网络只需建一次
docker network create intern-day-shared

# 2) 起后端
cd intern-day-2-backend
docker compose up -d --build

# 3) 起前端
cd ../intern-day-2-frontend
docker compose up -d --build
```

**关于模型**：本次账户余额为 0，真实模型调用会返回 `Insufficient Balance`。
演示时两种讲法，看你当时的情况：

- **有额度**：直接 `docker compose up -d`（不要带 `-f compose.mock.yaml`），走真实模型。
- **没额度**：后端用
  `docker compose -f compose.yaml -f compose.mock.yaml up -d --build`，
  开场就说「当前用的是本地 Mock 模型验证协议链路，真实模型因额度暂未接通」。
  **不要把它说成真实模型跑通**。

---

## 第一段：讲交互图（约 2 分钟）

打开 `intern-day-2-backend/docs/diagrams/day-3-agent-interaction.png`，
按图上 ①—⑥ 讲，每讲一层停一下：

> **「先说三个东西分别管什么。**
> Microsoft Agent Framework 管后端那个 Agent——它决定要不要调模型、要不要调工具。
> AG-UI 是前后端之间的**事件协议**，规定『开始跑了』『文字多了几个字』『工具调了』这些事件长什么样。
> CopilotKit 管前端和 Runtime 这一层，把聊天 UI 和事件流接起来。」

> 「**这里最容易搞混：AG-UI 不是传输方式。**
> 事件跑在 HTTP 上的 SSE 里。协议规定『说什么』，SSE 规定『怎么送』，HTTP 规定『怎么连』。
> 全程没有 WebSocket——就是一次普通 POST，响应不结束而已。」

然后指拓扑表：

> 「地址要分清三种：浏览器访问 `localhost:5173`；
> Runtime 在容器里是 `runtime:4000`；
> 它访问 Python 用的是共享网络里的服务名 `api:8000`，**不是** host.docker.internal。
> 这里我踩过坑，一会儿讲。」

---

## 第二段：登录 + 流式对话（约 1.5 分钟）

1. 打开 <http://localhost:5173>，用 `demo` / `.env` 里的 `SEED_PASSWORD` 登录。
   > 「登录用的是第二天的 Bearer 令牌，存 localStorage，每个请求带上。」

2. 点「新建对话」，输入「我11月花了多少钱？」，发送。

3. **在回复逐字出现时指着屏幕说**：
   > 「注意它不是等完整答案出来再显示。后端每产生一小段文本就通过 SSE 推一个
   > `TEXT_MESSAGE_CONTENT` 事件，前端收到就追加文字。」

4. 按 F12 → Network，找到 `/api/copilotkit` 请求：
   > 「看响应类型是 `text/event-stream`，这是 SSE。
   > 如果是 WebSocket，这里会是 `101 Switching Protocols` 和 upgrade 握手——这里没有。」

---

## 第三段：多轮上下文（约 1 分钟）

1. 输入「你好，我叫阿雪」，发送。
2. 紧接着输入「我叫什么名字？」，发送。

> 「第二轮它是从**这次请求带上来的历史消息**里读到『阿雪』的。
> 历史存在浏览器侧，每次全量发上来；后端不存对话历史。
> 所以如果我刷新页面，这段对话就没了——这是今天明确的取舍。」

---

## 第四段：工具调用（约 1.5 分钟）

1. 先到页面左侧「记一笔」加一笔支出，比如 12.34 元，日期选本月。
2. 回到聊天，问「我这个月花了多少钱？」

> 「这里重点看两件事：
> **第一，工具是后端真执行的**——它查的是 SQLite 里你刚记的那笔，
> 数字和我刚记的金额一致。不是我写死在提示词里的。
> **第二，用户身份不是模型给的**。模型只能填 `month` 参数，
> `user_id` 来自后端校验令牌后写进 `ContextVar` 的值。
> 模型想查别人的账也查不到。」

如果 Mock 模式，把后端日志亮出来（有 `TOOL_CALL_START` / `TOOL_CALL_RESULT`）：

```bash
cd intern-day-2-backend && docker logs intern-day-2-backend --tail 30
```

> 「日志里能看到 `TOOL_CALL_RESULT`，内容是真实的汇总数字。
> 这条日志里没有令牌、没有密钥。」

---

## 第五段：鉴权与错误路径（约 1.5 分钟）

**这一段的重点是「不能靠前端隐藏按钮」**：

```bash
# 不登录直接打 Agent 接口
curl -i -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"threadId":"t","runId":"r","state":{},"messages":[],"tools":[],"context":[],"forwardedProps":{}}'
```

> 「`401`，而且注意——**它连模型都没调**。鉴权在进入 Agent 之前就拦下了，
> 不会产生未授权的模型调用，也不烧钱。」

然后点「退出登录」，再点一次发送：

> 「退出后令牌被清掉，请求被拒，页面提示重新登录。」

**讲两类错误的区别**（这是我最想讲的一点）：

> 「失败有两种，处理方式完全不同：
> **建流之前失败** → HTTP 401，看状态码就行。
> **建流之后失败** → HTTP 仍然是 **200**，错误藏在 SSE 里的 `RUN_ERROR` 事件。
> 我一开始只判断状态码，结果模型出错时页面永远转圈——因为 200 看着是成功的。
> 这个只有把假密钥打进去、看原始 SSE 输出才能发现。」

---

## 第六段：代码与提交（约 1 分钟）

```bash
cd intern-day-2-backend && git log --oneline -8
cd ../intern-day-2-frontend && git log --oneline -6
```

> 「两个仓库各自的功能分支、分阶段提交。原理说明、交互图、复盘都在后端仓库：
> `docs/day-3-agent-learning.md`、`docs/diagrams/`、`docs/day-3-retrospective.md`。」

---

## 可能被问到的问题（准备好答案）

**Q：为什么用 `OpenAIChatCompletionClient` 而不是 `OpenAIChatClient`？**
> DeepSeek 这类兼容服务只实现了 `/chat/completions`，不支持 OpenAI 新的
> `/responses` 接口。用 `OpenAIChatClient` 会 404。

**Q：Runtime 会不会成为一个特权代理？**
> 不会。Runtime 按**每个请求**取出浏览器的 `Authorization` 头原样透传，
> 自己不存任何凭证，也不是「拿一个管理员 token 替所有人调用」。
> 真正的信任边界在 Python 后端。

**Q：threadId 能当凭证用吗？**
> 不能。threadId 是前端随机生成的标签，只用于会话分组。
> 数据权限只认 Bearer 令牌。

**Q：模型密钥怎么保证不进浏览器？**
> 只在后端容器的环境变量里。不进镜像构建参数（否则 `docker history` 能看到）、
> 不进 `VITE_*` 前端变量（会被编译进 JS 产物）、`.env` 在 `.gitignore` 和 `.dockerignore` 里。

**Q：`host.docker.internal` 那个问题具体是怎么回事？**
> 两个 Compose 项目默认网络互不可见。我一开始用 `host.docker.internal` 让
> Runtime 访问后端，结果 Authorization 头在转发中被本机代理改写丢失——
> 同一个合法令牌，走它得到 401，走 Docker 网关 `172.19.0.1` 得到 200。
> 后来改成显式共享网络，用服务名 `api:8000` 直连，问题消失。
