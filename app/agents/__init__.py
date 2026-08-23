"""Agent 节点：负责论文生成流水线中的各职责角色。"""

from app.agents.base import BaseAgent, get_llm
from app.agents.coordinator import PaperAssistantAgent
from app.agents.image_gen import ImageAgent
from app.agents.outline import OutlineAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.agents.summary import SummaryAgent

__all__ = [
    "BaseAgent",
    "get_llm",
    "PaperAssistantAgent",
    "OutlineAgent",
    "SummaryAgent",
    "ResearchAgent",
    "WriterAgent",
    "ReviewerAgent",
    "ImageAgent",
]
