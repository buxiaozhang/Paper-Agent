"""LangGraph 状态图构建：研究 -> 大纲 -> 撰写 -> 评审 -> 配图。

Agent 与工具实例通过闭包注入，避免将不可序列化对象放入共享状态。
"""

import logging

from langgraph.graph import END, START, StateGraph

from app.agents.outline import OutlineAgent
from app.agents.research import ResearchAgent, ReviewerAgent, WriterAgent
from app.agents.summary import SummaryAgent
from app.db.store import PaperStore
from app.graph.state import PaperState
from app.memory.short_term import ShortTermMemory, summary_key
from app.tools.literature import LiteratureSearchTool
from app.tools.outline import (
    DEFAULT_SECTIONS,
    flatten_subsection_titles,
    render_subsections,
    resolve_sections,
    split_structure,
)
from app.tools.template_index import TemplateIndex

logger = logging.getLogger(__name__)


def build_graph(
    researcher: ResearchAgent,
    outline_agent: OutlineAgent,
    writer: WriterAgent,
    reviewer: ReviewerAgent,
    summarizer: SummaryAgent,
    literature_tool: LiteratureSearchTool,
    short_memory: ShortTermMemory,
    store: PaperStore,
    template_index: TemplateIndex | None = None,
):
    """构建并编译论文生成流水线。"""

    def research_node(state: PaperState) -> dict:
        """研究节点：检索文献并生成研究背景。"""
        topic = state.get("topic", "")
        logger.info("节点开始：文献检索（主题：%s）", topic)
        references = literature_tool.search(topic, limit=10)
        if references:
            logger.info("节点完成：文献检索，命中 %d 篇文献", len(references))
            logger.info("文献内容：%s", references)
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
        structure = outline_agent.run(
            topic,
            base_sections,
            state.get("references"),
            state.get("template_hierarchy"),
        )
        sections, subsections_map = split_structure(structure)
        logger.info("生成的专属模板大纲%s", sections)
        logger.info("下级标题映射%s", subsections_map)
        logger.info("节点完成：大纲生成，共 %d 个章节", len(sections))
        title = f"{topic}：一项基于大四水平的软件工程专业的论文"
        paper_id = state.get("paper_id")
        if paper_id:
            # 大纲持久化到大纲表
            store.save_outline(paper_id, structure)
            store.update_record(paper_id, title=title, status="writing")
        return {
            # 一项基于多智能体协作的研究
            "title": title,
            "sections": sections,
            "section_subsections": subsections_map,
            "status": "outlining",
            "step": "大纲生成",
        }

    def writing_node(state: PaperState) -> dict:
        """撰写节点：按章节生成 / 修订草稿。"""
        topic = state.get("topic", "")
        feedback = state.get("feedback")
        sections = state.get("sections", DEFAULT_SECTIONS)
        references=state.get("references","未检索到相关文献")
        previous_summaries = state.get("section_summaries") or {}
        subsections_map = state.get("section_subsections") or {}
        revision = state.get("revision_count", 0) + 1
        template_id = state.get("template_id")
        readme_id = state.get("readme_id")
        logger.info("节点开始：论文撰写（第 %d 轮，章节数：%d）", revision, len(sections))
        parts, texts, summaries = [], [], {}
        for section_index, section in enumerate(sections, 1):
            subsections = subsections_map.get(section) or []
            template_examples: list[str] = []
            readme_examples: list[str] = []
            if template_index is not None:
                # 用「主题 + 章节 + 下级标题」检索模板写法 / README 项目背景参考
                subsection_titles = flatten_subsection_titles(subsections)
                query = " ".join(filter(None, [topic, section, *subsection_titles[:8]]))
                if template_id:
                    template_examples = template_index.search(template_id, query)
                if readme_id:
                    readme_examples = template_index.search(readme_id, query)
                if template_examples:
                    logger.info(
                        "章节「%s」检索到 %d 条模板写法参考",
                        section,
                        len(template_examples),
                    )
                if readme_examples:
                    logger.info(
                        "章节「%s」检索到 %d 条 README 参考",
                        section,
                        len(readme_examples),
                    )
            # 渲染带编号的下级标题，作为写作提示
            writer_subsections = render_subsections(section_index, subsections)
            # 将短期记忆传给大模型，只传关键信息摘要，避免上下文过长 / token 过多
            text = writer.run(
                topic,
                section,
                feedback,
                previous_summaries,
                writer_subsections,
                references,
                template_examples=template_examples,
                readme_examples=readme_examples,

            )
            texts.append(text)
            parts.append(f"## {section}\n{text}")
            # 将每一个大章节的内容只提取关键信息
            summaries[section] = summarizer.run(section, text)
        # 使用 Redis 存储：user_id + 论文主题
        user_id = state.get("user_id", "default")
        short_memory.set(summary_key(user_id, topic), summaries, ttl=86400)
        paper_id = state.get("paper_id")
        if paper_id:
            # 生成后的内容持久化到内容表
            store.save_sections(
                paper_id,
                [
                    {"title": s, "content": t, "summary": summaries[s]}
                    for s, t in zip(sections, texts)
                ],
            )
        logger.info("节点完成：论文撰写（第 %d 轮）", revision)
        return {
            "draft": "\n\n".join(parts),
            "section_summaries": summaries,
            "revision_count": revision,
            "status": "reviewing",
            "step": "论文撰写",
        }

    def review_node(state: PaperState) -> dict:
        """评审节点：质量检查，决定通过或退回修订。"""
        logger.info("节点开始：评审修订")
        passed, feedback = reviewer.run(
            state.get("topic", ""),
            state.get("draft", ""),
            state.get("section_summaries"),
        )
        if passed:
            logger.info("节点完成：评审通过")
            return {"feedback": "", "status": "done", "step": "评审修订"}
        logger.info("节点完成：评审未通过，退回撰写节点（意见长度：%d）", len(feedback))
        return {"feedback": feedback, "status": "draft", "step": "评审修订"}

    def image_node(state: PaperState) -> dict:
        """配图节点：为论文生成示意图（通义万相预留接口）。"""
        from app.agents.image_gen import ImageAgent

        logger.info("节点开始：配图生成")
        images = ImageAgent().run(state.get("topic", ""))
        # images = [{"status": "placeholder", "note": "暂时搁置生图agent"}]
        logger.info("节点完成：配图生成，返回 %d 条结果", len(images))
        return {"images": images, "step": "配图生成"}

    def should_continue(state: PaperState) -> str:
        """条件边：评审通过或达到修订上限则进入配图，否则回到撰写节点。"""
        if state.get("status") == "done":
            return "image"
        if state.get("revision_count", 0) >= state.get("max_revisions", 1):
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
