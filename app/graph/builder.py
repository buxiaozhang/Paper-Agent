"""LangGraph 状态图构建：研究 -> 大纲 -> 撰写 -> 评审 -> 配图。

Agent 与工具实例通过闭包注入，避免将不可序列化对象放入共享状态。
"""

import logging

from langgraph.graph import END, START, StateGraph

from app.agents.outline import OutlineAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.graph.state import PaperState
from app.tools.literature import LiteratureSearchTool
from app.tools.outline import DEFAULT_SECTIONS, resolve_sections

logger = logging.getLogger(__name__)


def build_graph(
    researcher: ResearchAgent,
    outline_agent: OutlineAgent,
    writer: WriterAgent,
    reviewer: ReviewerAgent,
    literature_tool: LiteratureSearchTool,
):
    """构建并编译论文生成流水线。"""

    def research_node(state: PaperState) -> dict:
        """研究节点：检索文献并生成研究背景。"""
        topic = state.get("topic", "")
        logger.info("节点开始：文献检索（主题：%s）", topic)
        references = literature_tool.search(topic, limit=5)
        logger.info("节点完成：文献检索，命中 %d 篇文献", len(references))
        researcher.run(topic, references)  # 生成背景综述（暂存于后续草稿流程）
        return {"references": references, "status": "researching", "step": "文献检索"}

    def outline_node(state: PaperState) -> dict:
        """大纲节点：以模板 / 默认大纲为参考，由 OutlineAgent 生成专属大纲。"""
        topic = state.get("topic", "")
        template_outline = state.get("template_outline")
        base_sections = resolve_sections(template_outline)
        logger.info(
            "节点开始：大纲生成（模板大纲：%s，参考章节数：%d）",
            "有" if template_outline else "无，使用默认",
            len(base_sections),
        )
        sections = outline_agent.run(topic, base_sections, state.get("references"))
        logger.info("节点完成：大纲生成，共 %d 个章节", len(sections))
        return {
            "title": f"{topic}：一项基于多智能体协作的研究",
            "sections": sections,
            "status": "outlining",
            "step": "大纲生成",
        }

    def writing_node(state: PaperState) -> dict:
        """撰写节点：按章节生成 / 修订草稿。"""
        topic = state.get("topic", "")
        feedback = state.get("feedback")
        sections = state.get("sections", DEFAULT_SECTIONS)
        revision = state.get("revision_count", 0) + 1
        logger.info("节点开始：论文撰写（第 %d 轮，章节数：%d）", revision, len(sections))
        parts = []
        for section in sections:
            parts.append(f"## {section}\n{writer.run(topic, section, feedback)}")
        logger.info("节点完成：论文撰写（第 %d 轮）", revision)
        return {
            "draft": "\n\n".join(parts),
            "revision_count": revision,
            "status": "reviewing",
            "step": "论文撰写",
        }

    def review_node(state: PaperState) -> dict:
        """评审节点：质量检查，决定通过或退回修订。"""
        logger.info("节点开始：评审修订")
        passed, feedback = reviewer.run(state.get("topic", ""), state.get("draft", ""))
        if passed:
            logger.info("节点完成：评审通过")
            return {"feedback": "", "status": "done", "step": "评审修订"}
        logger.info("节点完成：评审未通过，退回撰写节点（意见长度：%d）", len(feedback))
        return {"feedback": feedback, "status": "draft", "step": "评审修订"}

    def image_node(state: PaperState) -> dict:
        """配图节点：为论文生成示意图（通义万相预留接口）。"""
        from app.agents.image_gen import ImageAgent

        logger.info("节点开始：配图生成")
        # images = ImageAgent().run(state.get("topic", ""))
        images="暂时搁置生图agent"
        logger.info("节点完成：配图生成，返回 %d 条结果", len(images))
        return {"images": images, "step": "配图生成"}

    def should_continue(state: PaperState) -> str:
        """条件边：评审通过或达到修订上限则进入配图，否则回到撰写节点。"""
        if state.get("status") == "done":
            return "image"
        if state.get("revision_count", 0) >= state.get("max_revisions", 2):
            return "image"
        return "writer"

    builder = StateGraph(PaperState)
    builder.add_node("researcher", research_node)
    builder.add_node("outline", outline_node)
    builder.add_node("writer", writing_node)
    builder.add_node("reviewer", review_node)
    builder.add_node("image", image_node)

    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "outline")
    builder.add_edge("outline", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        should_continue,
        {"writer": "writer", "image": "image"},
    )
    builder.add_edge("image", END)

    return builder.compile()
