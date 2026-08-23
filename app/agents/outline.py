"""大纲 Agent：基于论文主题与参考大纲，生成专属章节大纲。"""

import logging
import re

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_NUMBERED_LINE = re.compile(
    r"^\s*[（(]?(?:\d+|[一二三四五六七八九十百]+|第[一二三四五六七八九十百]+章)"
    r"[)）]?\s*[.、:：)）]?\s*(.+?)\s*$"
)
_MAX_SECTIONS = 12
_MIN_SECTIONS = 2
_MAX_TITLE_LENGTH = 40


class OutlineAgent(BaseAgent):
    """大纲生成与优化 Agent：将模板 / 默认大纲优化为紧扣主题的专属大纲。"""

    name = "outliner"
    description = "大纲生成与优化 Agent"

    def run(
        self,
        topic: str,
        base_sections: list[str],
        references: list[dict] | None = None,
    ) -> list[str]:
        """生成专属大纲；LLM 输出不可用时回退参考大纲。"""
        base_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(base_sections))
        ref_text = ""
        if references:
            titles = [r.get("title", "") for r in references[:5] if r.get("title")]
            if titles:
                ref_text = "\n".join(f"- {t}" for t in titles)
        prompt = (
            # 学术论文写作专家
            "你是一名大四软件工程学生。请根据论文主题和参考大纲，生成一份专属于该论文的章节大纲。\n"
            f"论文主题：{topic}\n"
            f"参考大纲（可能来自论文模板或默认结构）：\n{base_text}\n"
        )
        if ref_text:
            prompt += f"已检索到的相关文献（可作参考）：\n{ref_text}\n"
        prompt += (
            "要求：\n"
            "1. 紧扣主题：删除与主题无关的章节，补充主题所需的章节，可调整顺序与命名；\n"
            "2. 章节数量适中（建议 5-10 个）；\n"
            "3. 只输出章节标题，每行一个，格式为“数字. 标题”，不要输出其他说明。"
        )
        logger.info(
            "大纲优化：调用 LLM 生成专属大纲（主题：%s，参考章节数：%d）",
            topic,
            len(base_sections),
        )
        response = str(self.llm.invoke(prompt).content)
        sections = parse_sections(response)
        if sections:
            logger.info("大纲优化完成：生成 %d 个章节", len(sections))
            return sections
        logger.warning(
            "大纲优化失败或输出无法解析，回退参考大纲（%d 个章节）",
            len(base_sections),
        )
        return base_sections


def parse_sections(text: str) -> list[str] | None:
    """解析 LLM 输出的大纲文本，返回章节列表；无法解析时返回 None。"""
    lines = [line.strip() for line in (text or "").splitlines()]
    sections: list[str] = []
    for line in lines:
        match = _NUMBERED_LINE.match(line)
        if not match:
            continue
        title = _clean_title(match.group(1))
        if title and len(title) <= _MAX_TITLE_LENGTH:
            sections.append(title)
    if not sections:
        # 二级解析：接受 Markdown 列表 / 标题行（如 "- 引言"）
        for line in lines:
            stripped = line.lstrip("-*# ")
            if not stripped or stripped == line:
                continue
            title = _clean_title(stripped)
            if title and len(title) <= _MAX_TITLE_LENGTH:
                sections.append(title)
    sections = _dedupe(sections)[:_MAX_SECTIONS]
    return sections if len(sections) >= _MIN_SECTIONS else None


def _clean_title(title: str) -> str:
    """去除标题中的 Markdown 标记字符。"""
    return re.sub(r"[*_`#]", "", title).strip()


def _dedupe(items: list[str]) -> list[str]:
    """按顺序去重并过滤空串。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
