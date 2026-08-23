"""论文生成流水线的主协调 Agent（薄封装，供 API/UI 调用）。"""

import logging
from collections.abc import Callable

from app.agents.image_gen import ImageAgent
from app.agents.outline import OutlineAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.config import setup_logging
from app.graph.builder import build_graph
from app.tools.literature import LiteratureSearchTool

setup_logging()
logger = logging.getLogger(__name__)

# 进度回调签名：progress_callback(percent: int, step_name: str)
ProgressCallback = Callable[[int, str], None]


class PaperAssistantAgent:
    """论文辅助生成入口：检索 -> 撰写 -> 评审 -> 配图。"""

    def __init__(self) -> None:
        self.researcher = ResearchAgent()
        self.writer = WriterAgent()
        self.reviewer = ReviewerAgent()
        self.illustrator = ImageAgent()
        self.outliner = OutlineAgent()
        self.literature = LiteratureSearchTool()
        self.graph = build_graph(
            researcher=self.researcher,
            outline_agent=self.outliner,
            writer=self.writer,
            reviewer=self.reviewer,
            literature_tool=self.literature,
        )

    def generate(
        self,
        topic: str,
        max_revisions: int = 2,
        template_outline: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        """执行论文生成流水线并返回最终状态。

        Args:
            topic: 论文主题。
            max_revisions: 评审-修订最大轮数。
            template_outline: 从上传模板提取的大纲；为 None 时使用默认大纲。
            progress_callback: 进度回调，参数为 (百分比, 当前步骤名)。
        """
        logger.info(
            "论文生成流水线启动：主题=%s，最大修订轮数=%d，模板大纲=%s",
            topic,
            max_revisions,
            "有" if template_outline else "无（使用默认大纲）",
        )
        # 预估总步数：检索 / 大纲 / 撰写 / 评审 / 配图 + 每次修订的撰写与评审
        total_steps = 5 + max_revisions * 2
        visited = 0
        result = None
        initial_state = {
            "topic": topic,
            "max_revisions": max_revisions,
            "draft": "",
            "template_outline": template_outline,
        }
        for state in self.graph.stream(initial_state, stream_mode="values"):
            step_name = state.get("step")
            if not step_name:
                continue  # 首个 chunk 为输入状态，无 step 字段
            visited += 1
            percent = min(int(visited / total_steps * 100), 100)
            logger.info("STEP %d/%d（%d%%）| %s", visited, total_steps, percent, step_name)
            if progress_callback:
                progress_callback(percent, step_name)
            result = state
        if progress_callback:
            progress_callback(100, "生成完成")
        logger.info("论文生成流水线完成（共执行 %d 个节点）", visited)
        result = result or {}
        return {
            "topic": topic,
            "title": result.get("title", topic),
            "sections": result.get("sections", []),
            "draft": result.get("draft", ""),
            "references": result.get("references", []),
            "images": result.get("images", []),
            "status": result.get("status", "draft"),
        }
