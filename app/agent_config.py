"""运行配置扩展：Agent（模型服务）相关设置。

模型密钥只从后端环境变量 / .env 读取，绝不进入镜像构建参数、前端环境变量或浏览器。
DeepSeek 提供 OpenAI 兼容接口，因此用 agent-framework-openai 的 OpenAIChatClient
加 base_url 接入；如果导师换成 OpenAI/Azure OpenAI，只需改这三个变量。
"""

from __future__ import annotations

import os


class AgentSettings:
    def __init__(self) -> None:
        self.api_key = os.getenv("MODEL_API_KEY", "")
        self.base_url = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com/v1")
        self.model = os.getenv("MODEL_ID", "deepseek-chat")

    @property
    def enabled(self) -> bool:
        """未配置密钥时不注册 /agent 端点，保证原有服务照常启动。"""
        return bool(self.api_key)

    @property
    def is_local_base_url(self) -> bool:
        """允许非 https 的本机 / 容器内 Mock 地址。

        真实模型服务必须 https：密钥与提示词都会经过这条连接，明文传输不可接受。
        但以下场景走明文是合理的，且都只在本机或自有容器网络内：

        - http://localhost / http://127.0.0.1：本机直接跑 Mock 或 Ollama
        - http://mock:8899：`compose.mock.yaml` 里同项目的 Mock 服务
          （容器内服务名，不出宿主机）

        除此之外一律要求 https，避免有人把公司内网服务误配成明文。
        """
        lowered = self.base_url.lower()
        return lowered.startswith(
            ("http://localhost", "http://127.0.0.1", "http://mock:")
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.api_key:
            problems.append(
                "缺少 MODEL_API_KEY。请在后端仓库根目录的 .env 里配置模型服务密钥"
                "（DeepSeek 为例：MODEL_API_KEY=sk-...）。未配置时 /agent 端点不会注册。"
            )
        if not self.base_url.lower().startswith("https://") and not self.is_local_base_url:
            problems.append(
                "MODEL_BASE_URL 必须是 https:// 开头的服务地址"
                "（仅本机 Mock 允许 http://localhost 或 http://127.0.0.1）。"
            )
        if not self.model:
            problems.append("MODEL_ID 不能为空。")
        return problems
