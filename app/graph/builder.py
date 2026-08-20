"""LangGraph 状态图构建：研究 -> 大纲 -> 撰写 -> 评审 -> 配图。

Agent 与工具实例通过闭包注入，避免将不可序列化对象放入共享状态。
"""

from langgraph.graph import END, START, StateGraph

from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.graph.state import PaperState
from app.tools.literature import LiteratureSearchTool

DEFAULT_SECTIONS = ["引言", "相关工作", "方法", "实验与结果", "结论"]


def build_graph(
    researcher: ResearchAgent,
    writer: WriterAgent,
    reviewer: ReviewerAgent,
    literature_tool: LiteratureSearchTool,
):
    """构建并编译论文生成流水线。"""

    def research_node(state: PaperState) -> dict:
        """研究节点：检索文献并生成研究背景。"""
        topic = state.get("topic", "")
        references = literature_tool.search(topic, limit=5)
        researcher.run(topic, references)  # 生成背景综述（暂存于后续草稿流程）
        return {"references": references, "status": "researching"}

    def outline_node(state: PaperState) -> dict:
        """大纲节点：确定标题与章节结构（可替换为 LLM 生成）。"""
        topic = state.get("topic", "")
        return {
            "title": f"{topic}：一项基于多智能体协作的研究",
            "sections": DEFAULT_SECTIONS,
            "status": "outlining",
        }

    def writing_node(state: PaperState) -> dict:
        """撰写节点：按章节生成 / 修订草稿。"""
        topic = state.get("topic", "")
        feedback = state.get("feedback")
        sections = state.get("sections", DEFAULT_SECTIONS)
        parts = []
        for section in sections:
            parts.append(f"## {section}\n{writer.run(topic, section, feedback)}")
        return {
            "draft": "\n\n".join(parts),
            "revision_count": state.get("revision_count", 0) + 1,
            "status": "reviewing",
        }

    def review_node(state: PaperState) -> dict:
        """评审节点：质量检查，决定通过或退回修订。"""
        passed, feedback = reviewer.run(state.get("topic", ""), state.get("draft", ""))
        if passed:
            return {"feedback": "", "status": "done"}
        return {"feedback": feedback, "status": "draft"}

    def image_node(state: PaperState) -> dict:
        """配图节点：为论文生成示意图（通义万相预留接口）。"""
        from app.agents.image_gen import ImageAgent

        images = ImageAgent().run(state.get("topic", ""))
        return {"images": images}

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
