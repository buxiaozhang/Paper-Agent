"""论文生成流水线的主协调 Agent（薄封装，供 API/UI 调用）。"""

from app.agents.image_gen import ImageAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.graph.builder import build_graph
from app.tools.literature import LiteratureSearchTool


class PaperAssistantAgent:
    """论文辅助生成入口：检索 -> 撰写 -> 评审 -> 配图。"""

    def __init__(self) -> None:
        self.researcher = ResearchAgent()
        self.writer = WriterAgent()
        self.reviewer = ReviewerAgent()
        self.illustrator = ImageAgent()
        self.literature = LiteratureSearchTool()
        self.graph = build_graph(
            researcher=self.researcher,
            writer=self.writer,
            reviewer=self.reviewer,
            literature_tool=self.literature,
        )

    def generate(self, topic: str, max_revisions: int = 2) -> dict:
        """执行论文生成流水线并返回最终状态。"""
        result = self.graph.invoke(
            {"topic": topic, "max_revisions": max_revisions, "draft": ""}
        )
        return {
            "topic": topic,
            "title": result.get("title", topic),
            "sections": result.get("sections", []),
            "draft": result.get("draft", ""),
            "references": result.get("references", []),
            "images": result.get("images", []),
            "status": result.get("status", "draft"),
        }
