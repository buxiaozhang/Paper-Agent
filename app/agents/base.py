"""Agent 基类：提供共享 LLM 初始化与统一的运行入口。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(model: str | None = None, temperature: float | None = None) -> BaseChatModel:
    """按配置创建 LLM。

    默认使用 DeepSeek（OpenAI 兼容接口）；将 LLM_PROVIDER 设为 openai
    并配置 OPENAI_API_KEY 后可切换到 GPT-4o 等 OpenAI 模型。
    """
    if settings.llm_provider == "openai":
        return ChatOpenAI(
            model=model or settings.default_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=temperature if temperature is not None else settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    return ChatOpenAI(
        model=model or settings.default_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature if temperature is not None else settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )


class BaseAgent:
    """所有论文生成 Agent 的基类。"""

    name: str = "base"
    description: str = "基础 Agent"

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self.llm = llm or get_llm()
