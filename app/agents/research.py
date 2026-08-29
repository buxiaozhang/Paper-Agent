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
            f"参考以下文献：\n{ref_text or '（如果没有文献，则不在使用文献，不可自己生成文献）'}"
        )
        response = self.llm.invoke(prompt)
        return str(response.content)


class WriterAgent(BaseAgent):
    """论文撰写 Agent：按大纲生成 / 修订章节正文。"""

    name = "writer"
    description = "论文正文撰写 Agent"

    def run(
        self,
        topic: str,
        section: str,
        feedback: str | None = None,
        section_summaries: dict[str, str] | None = None,
        subsections: list[str] | None = None,
        references: list[str] | None = None,
        template_examples: list[str] | None = None,
        readme_examples: list[str] | None = None,
    ) -> str:
        """生成单个章节的正文。

        Args:
            section_summaries: 此前各章节的关键信息摘要，用于保持连贯、
                避免重复（防止直接拼接全文导致上下文爆炸）。
            subsections: 本节参考下级标题（写作提示，内容应覆盖这些要点）。
            template_examples: 从向量库检索到的模板相近章节片段（仅借鉴
                结构、措辞风格与论证思路，不得照抄）。
            readme_examples: 从向量库检索到的 README 背景/需求片段（结合
                主题组织进论文，用作项目背景与功能点依据，不得照抄原文）。
        """
        # 学术写作助手
        prompt = (
            f"你是一名即将毕业的大四软件工程的优秀学生，请为论文「{topic}」撰写章节「{section}」的正文，"
            f"如果本章节是文献的话，请将{references}中的文献输入，而不是自己构建文献"
            "要求学术规范、语言严谨。"
        )
        if feedback:
            prompt += f"\n评审意见：{feedback}\n请据此修订。"
        if section_summaries:
            context = "\n".join(f"- {t}: {s}" for t, s in section_summaries.items())
            prompt += f"\n此前各章节关键信息（保持连贯、避免重复）：\n{context}"
        if subsections:
            subs_text = "\n".join(f"- {s}" for s in subsections)
            prompt += f"\n本节参考下级标题（内容应覆盖这些要点）：\n{subs_text}"
        if template_examples:
            examples_text = "\n\n".join(
                f"【模板参考 {i}】{example[:800]}"
                for i, example in enumerate(template_examples, 1)
            )
            prompt += (
                "\n以下是与本章节内容相近的模板写法片段（仅借鉴其结构、"
                "措辞风格与论证思路，内容必须围绕本论文主题原创，严禁照抄原文）：\n"
                f"{examples_text}"
            )
        if readme_examples:
            readme_text = "\n\n".join(
                f"【README 参考 {i}】{example[:800]}"
                for i, example in enumerate(readme_examples, 1)
            )
            prompt += (
                "\n以下是从项目 README 中检索到的背景/需求片段（请据此组织项目背景、"
                "功能点与技术要求，用论文语言表达，严禁照抄原文）：\n"
                f"{readme_text}"
            )
        response = self.llm.invoke(prompt)
        return str(response.content)


class ReviewerAgent(BaseAgent):
    """评审 Agent：对草稿进行质量检查并给出修改意见。"""

    name = "reviewer"
    description = "论文评审与质量检查 Agent"

    def run(
        self,
        topic: str,
        draft: str,
        section_summaries: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """评审草稿，返回 (是否通过, 修改意见)。

        Args:
            section_summaries: 各章节关键信息摘要；提供时以摘要为主、
                草稿片段为辅，避免全文进入上下文。
        """
        if section_summaries:
            summary_text = "\n".join(f"- {t}: {s}" for t, s in section_summaries.items())
            prompt = (
                f"你是严格的学术审稿人，请评审论文「{topic}」。\n"
                f"各章节关键信息摘要：\n{summary_text}\n\n"
                f"草稿片段（供抽查）：\n{draft[:3000]}\n\n"
                "若质量达标请仅回复 PASS，否则回复 REVISE 并列出具体修改意见。"
            )
        else:
            prompt = (
                f"你是严格的学术审稿人，请评审论文「{topic}」的草稿：\n{draft[:6000]}\n\n"
                "若质量达标请仅回复 PASS，否则回复 REVISE 并列出具体修改意见。"
            )
        response = str(self.llm.invoke(prompt).content)
        if response.strip().upper().startswith("PASS"):
            return True, ""
        return False, response
