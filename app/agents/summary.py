"""摘要 Agent：将章节内容压缩为关键信息，防止上下文爆炸。"""

from app.agents.base import BaseAgent


class SummaryAgent(BaseAgent):
    """章节关键信息提取 Agent：供短期记忆与后续撰写 / 评审使用。"""

    name = "summarizer"
    description = "章节关键信息摘要 Agent"

    def run(self, section_title: str, section_text: str) -> str:
        """把章节正文压缩为不超过 150 字的关键信息摘要。"""
        prompt = (
            "你是学术写作助手。请将以下论文章节内容压缩为关键信息摘要（不超过 150 字），"
            "保留核心观点、方法与结论，用于后续章节写作时保持上下文连贯。只输出摘要文本：\n"
            f"章节标题：{section_title}\n"
            f"章节内容：\n{section_text[:4000]}"
        )
        return str(self.llm.invoke(prompt).content).strip()
