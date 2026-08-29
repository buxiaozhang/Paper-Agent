"""论文生成流水线的主协调 Agent（薄封装，供 API/UI 调用）。"""

import logging
from collections.abc import Callable
from datetime import datetime

from app.agents.image_gen import ImageAgent
from app.agents.outline import OutlineAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.agents.summary import SummaryAgent
from app.config import setup_logging
from app.db.store import PaperStore
from app.graph.builder import build_graph
from app.memory.short_term import ShortTermMemory, lock_key
from app.tools.literature import LiteratureSearchTool
from app.tools.template_index import TemplateIndex

setup_logging()
logger = logging.getLogger(__name__)

# 进度回调签名：progress_callback(percent: int, step_name: str)
ProgressCallback = Callable[[int, str], None]


class PaperBusyError(RuntimeError):
    """同一用户已有论文生成任务进行中。"""


class PaperAssistantAgent:
    """论文辅助生成入口：检索 -> 撰写 -> 评审 -> 配图。"""

    def __init__(
        self,
        short_memory: ShortTermMemory | None = None,
        store: PaperStore | None = None,
    ) -> None:
        """初始化流水线；可注入共享的 Redis 记忆与数据库存储实例。"""
        self.researcher = ResearchAgent()
        self.writer = WriterAgent()
        self.reviewer = ReviewerAgent()
        self.illustrator = ImageAgent()
        self.outliner = OutlineAgent()
        self.summarizer = SummaryAgent()
        self.literature = LiteratureSearchTool()
        self.short_memory = short_memory or ShortTermMemory()
        self.store = store or PaperStore()
        self.store.init_db()
        self.template_index = TemplateIndex()
        self.graph = build_graph(
            researcher=self.researcher,
            outline_agent=self.outliner,
            writer=self.writer,
            reviewer=self.reviewer,
            summarizer=self.summarizer,
            literature_tool=self.literature,
            short_memory=self.short_memory,
            store=self.store,
            template_index=self.template_index,
        )

    def generate(
        self,
        topic: str,
        max_revisions: int = 2,
        template_outline: list[str] | None = None,
        template_hierarchy: list[dict] | None = None,
        template_id: str | None = None,
        readme_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
        user_id: str = "default",
    ) -> dict:
        """执行论文生成流水线并返回最终状态。

        Args:
            topic: 论文主题。
            max_revisions: 评审-修订最大轮数。
            template_outline: 从上传模板提取的大纲；为 None 时使用默认大纲。
            template_hierarchy: 模板层级（一级 + 二级标题），作为大纲 Agent 的参考。
            template_id: 模板切片在向量库中的 ID；提供时写作阶段会检索模板写法参考。
            readme_id: README 切片在向量库中的 ID；提供时写作阶段会检索项目背景/需求参考。
            progress_callback: 进度回调，参数为 (百分比, 当前步骤名)。
            user_id: 用户 ID（用于锁、进度与历史记录）。
        """
        # 用户级互斥：一个用户同时只能生成一篇论文
        if not self.short_memory.acquire_lock(lock_key(user_id)):
            logger.warning("用户 %s 已有论文生成任务进行中，拒绝新任务", user_id)
            raise PaperBusyError(f"用户 {user_id} 已有论文生成任务进行中，请等待完成")

        paper_id: int | None = None
        current_percent = 0

        def emit(percent: int, step: str, status: str = "running") -> None:
            """进度同时写入 Redis（支持刷新恢复）并触发回调。"""
            nonlocal current_percent
            current_percent = percent
            self.short_memory.set_progress(
                user_id,
                topic,
                {
                    "paper_id": paper_id,
                    "user_id": user_id,
                    "topic": topic,
                    "percent": percent,
                    "step": step,
                    "status": status,
                    "updated_at": datetime.utcnow().isoformat(),
                },
                ttl=86400,
            )
            if progress_callback:
                progress_callback(percent, step)

        logger.info(
            "论文生成流水线启动：用户=%s，主题=%s，最大修订轮数=%d，模板大纲=%s",
            user_id,
            topic,
            max_revisions,
            "有" if template_outline else "无（使用默认大纲）",
        )
        try:
            # 历史表：新建生成记录
            paper_id = self.store.create_record(user_id, topic)
            emit(0, "准备开始")
            # 预估总步数：检索 / 大纲 / 撰写 / 评审 / 配图 + 每次修订的撰写与评审；
            # 单轮（max_revisions <= 1）时跳过评审，仅 检索 / 大纲 / 撰写 / 配图 四步。
            total_steps = 4 if max_revisions <= 1 else 3 + max_revisions * 2
            visited = 0
            result = None
            initial_state = {
                "topic": topic,
                "user_id": user_id,
                "paper_id": paper_id,
                "max_revisions": max_revisions,
                "draft": "",
                "template_outline": template_outline,
                "template_hierarchy": template_hierarchy,
                "template_id": template_id,
                "readme_id": readme_id,
            }
            for state in self.graph.stream(initial_state, stream_mode="values"):
                step_name = state.get("step")
                if not step_name:
                    continue  # 首个 chunk 为输入状态，无 step 字段
                visited += 1
                percent = min(int(visited / total_steps * 100), 100)
                logger.info("STEP %d/%d（%d%%）| %s", visited, total_steps, percent, step_name)
                emit(percent, step_name)
                result = state
            self.store.update_record(paper_id, status="completed")
            emit(100, "生成完成", "done")
            logger.info("论文生成流水线完成（共执行 %d 个节点）", visited)
            result = result or {}
            return {
                "paper_id": paper_id,
                "topic": topic,
                "title": result.get("title", topic),
                "sections": result.get("sections", []),
                "draft": result.get("draft", ""),
                "references": result.get("references", []),
                "images": result.get("images", []),
                "status": result.get("status", "draft"),
            }
        except Exception:
            logger.exception("论文生成流水线失败：用户=%s，主题=%s", user_id, topic)
            if paper_id:
                self.store.update_record(paper_id, status="error")
            emit(current_percent, "生成失败", "error")
            raise
        finally:
            self.short_memory.release_lock(lock_key(user_id))
