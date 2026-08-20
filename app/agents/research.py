"""研究 Agent：文献检索与背景调研。"""

from app.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    """检索相关文献并整理研究背景与相关工作。"""

    name = "researcher"
    description = "文献检索与背景调研 Agent"

    def run(self, topic: str, literature: list[dict] | None = None) -> str:
        """基于检索到的文献生成研究背景综述。

        Args:
            topic: 论文主题。
            literature: 检索工具返回的文献列表（可选）。
        """
        references = literature or []
        ref_text = "\n".join(
            f"- {item.get('title', '')} ({item.get('year', '')})" for item in references[:10]
        )
        prompt = (
            f"你是学术研究助手，请围绕主题「{topic}」撰写研究背景与相关工作综述。\n"
            f"参考以下文献：\n{ref_text or '（暂无检索结果，请给出一般性背景介绍）'}"
        )
        response = self.llm.invoke(prompt)
        return str(response.content)


class WriterAgent(BaseAgent):
    """论文撰写 Agent：按大纲生成 / 修订章节正文。"""

    name = "writer"
    description = "论文正文撰写 Agent"

    def run(self, topic: str, section: str, feedback: str | None = None) -> str:
        """生成单个章节的正文。"""
        prompt = (
            f"你是学术写作助手，请为论文「{topic}」撰写章节「{section}」的正文，"
            "要求学术规范、语言严谨。"
        )
        if feedback:
            prompt += f"\n评审意见：{feedback}\n请据此修订。"
        response = self.llm.invoke(prompt)
        return str(response.content)


class ReviewerAgent(BaseAgent):
    """评审 Agent：对草稿进行质量检查并给出修改意见。"""

    name = "reviewer"
    description = "论文评审与质量检查 Agent"

    def run(self, topic: str, draft: str) -> tuple[bool, str]:
        """评审草稿，返回 (是否通过, 修改意见)。"""
        prompt = (
            f"你是严格的学术审稿人，请评审论文「{topic}」的草稿：\n{draft[:6000]}\n\n"
            "若质量达标请仅回复 PASS，否则回复 REVISE 并列出具体修改意见。"
        )
        response = str(self.llm.invoke(prompt).content)
        if response.strip().upper().startswith("PASS"):
            return True, ""
        return False, response
