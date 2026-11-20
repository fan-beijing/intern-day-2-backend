# 开发容器实测记录（2026-11-20）

方式：用官方 `@devcontainers/cli`（0.90.0）执行 `devcontainer up --workspace-folder <本仓库>`，
与 VS Code「Dev Containers: Reopen in Container」走同一构建与生命周期
（构建 `.devcontainer/Dockerfile` → 创建容器 → 跑 `devcontainer.json` 的 `postCreateCommand`），
结果可完全复现。

## 1. 构建与启动

```text
$ devcontainer up --workspace-folder intern-day-2-backend
（镜像构建成功；postCreateCommand: uv sync --frozen —— 成功）
{"outcome":"success","remoteUser":"root","remoteWorkspaceFolder":"/workspaces/intern-day-2-backend"}
```

## 2. 容器内工具版本（`docker exec <容器> bash -lc ...`）

```text
python: Python 3.13.18
uv:     uv 0.13.8 (x86_64-unknown-linux-gnu)
git:    git version 2.47.3
```

## 3. 容器内安装与测试

`uv sync --frozen` 按锁文件装入 30 个包（fastapi 0.163.1 / sqlalchemy 2.1.8 / bcrypt 5.0.0 /
httpx2 2.16.0 / pytest 8.4.2 等）。随后：

```text
$ uv run pytest
................                                                         [100%]
16 passed in 9.52s
```

## 4. 复现命令

```bash
npx @devcontainers/cli up --workspace-folder <仓库路径>
docker exec <容器ID> bash -lc 'cd /workspaces/intern-day-2-backend && uv --version && uv run pytest'
```
