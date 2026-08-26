"""应用全局配置管理。

通过 pydantic-settings 从环境变量 / .env 文件加载配置，
集中管理 API Keys、Redis、数据库、ChromaDB、OSS 与通义万相等连接信息。
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志配置（幂等，可在 API / UI 入口重复调用）。"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class Settings(BaseSettings):
    """全局配置。字段名自动映射为同名（大写）环境变量。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- LLM ----------
    llm_provider: Literal["deepseek", "openai"] = "deepseek"
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_base_url: str = "https://api.openai.com/v1"
    default_model: str = "deepseek-chat"       # 也可配置为 gpt-4o
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096


    # ---------- 数据存储 ----------
    redis_url: str = "redis://localhost:6379/0"
    # 开发环境默认 SQLite；生产环境可改为 postgresql+asyncpg://...
    # MySQL 示例：mysql+pymysql://user:password@localhost:3306/paper_agent
    database_url: str = "sqlite:///./paper_agent.db"

    # ---------- 向量数据库 ----------
    chroma_dir: str = "./data/chroma"
    chroma_collection: str = "paper_agent_memory"
    template_chunk_size: int = 800   # 模板切片大小（字符）
    template_chunk_overlap: int = 100  # 固定长度切片的重叠字符（PDF 等无标题场景）
    template_top_k: int = 3          # 撰写每个章节时检索的模板参考片段数

    # ---------- 对象存储 OSS ----------
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_endpoint: str = "oss-cn-hangzhou.aliyuncs.com"
    oss_bucket: str = "paper-agent"

    # ---------- 图片生成：阿里云通义万相 ----------
    aliyun_dashscope_api_key: str | None = None
    aliyun_wanx_model: str = "wanx-v1"

    # ---------- 文献检索 ----------
    openalex_base_url: str = "https://api.openalex.org"
    semantic_scholar_base_url: str = "https://api.semanticscholar.org"
    semantic_scholar_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """返回全局唯一的 Settings 实例（进程内缓存）。"""
    return Settings()


settings = get_settings()
