"""大纲 Agent：基于论文主题与参考大纲，生成专属层级大纲（一级 + 二级标题）。"""

import logging
import re

from app.agents.base import BaseAgent
from app.tools.outline import hierarchy_to_text

logger = logging.getLogger(__name__)

_NUMBERED_LINE = re.compile(
    r"^\s*[（(]?(\d+(?:\.\d+)*)[)）]?\s*[.、:：)）]?\s*(.+?)\s*$"
)
_MAX_SECTIONS = 12
_MIN_SECTIONS = 2
_MAX_TITLE_LENGTH = 40
_MAX_SUBSECTIONS = 6


class OutlineAgent(BaseAgent):
    """大纲生成与优化 Agent：生成紧扣主题的一级大纲，并给出二级标题。"""

    name = "outliner"
    description = "大纲生成与优化 Agent"

    def run(
        self,
        topic: str,
        base_sections: list[str],
        references: list[dict] | None = None,
        template_hierarchy: list[dict] | None = None,
    ) -> list[dict]:
        """生成专属层级大纲：[{"title": 一级标题, "subsections": [二级标题...]}, ...]。

        Args:
            template_hierarchy: 模板的完整层级（一级 + 二级），作为二级标题的参考；
                未提供时仅按主题与一级参考大纲生成。
        """
        base_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(base_sections))
        template_text = hierarchy_to_text(template_hierarchy)
        ref_text = ""
        if references:
            titles = [r.get("title", "") for r in references[:5] if r.get("title")]
            if titles:
                ref_text = "\n".join(f"- {t}" for t in titles)
        prompt = (
            "你是学术论文写作专家。请根据论文主题和参考大纲，生成一份专属于该论文的章节大纲，"
            "包含一级标题和每个一级标题下的二级标题。\n"
            f"论文主题：{topic}\n"
            f"参考大纲（可能来自论文模板或默认结构）：\n{base_text}\n"
        )
        if template_text:
            prompt += f"模板的完整层级结构（二级标题的重要参考）：\n{template_text}\n"
        if ref_text:
            prompt += f"已检索到的相关文献（可作参考）：\n{ref_text}\n"
        prompt += (
            "要求：\n"
            "1. 一级标题紧扣主题（可参考模板一级标题），删除与主题无关的章节；\n"
            "2. 每个一级标题下给出 2-4 个二级标题，优先沿用模板对应的二级标题结构，"
            "结合主题适当调整；\n"
            "3. 章节数量适中（一级标题建议 5-10 个）；\n"
            "4. 每行一个标题，用编号层级表示级别，例如：\n"
            "1. 引言\n1.1 研究背景\n1.2 研究意义\n2. 相关工作\n2.1 国内研究现状\n"
            "只输出标题，不要输出其他说明。"
        )
        logger.info(
            "大纲优化：调用 LLM 生成专属层级大纲（主题：%s，参考一级章节数：%d，模板层级：%s）",
            topic,
            len(base_sections),
            "有" if template_hierarchy else "无",
        )
        response = str(self.llm.invoke(prompt).content)
        structure = parse_structure(response)
        logger.info("生成的大纲 章节：%s",structure)
        if not structure:
            logger.warning(
                "大纲优化失败或输出无法解析，回退参考大纲（%d 个一级章节）",
                len(base_sections),
            )
            structure = fallback_structure(base_sections, template_hierarchy)
        structure = enrich_subsections(structure, template_hierarchy)
        logger.info(
            "大纲优化完成：%d 个一级章节，二级标题共 %d 个",
            len(structure),
            sum(len(item.get("subsections", [])) for item in structure),
        )

        return structure


def parse_structure(text: str) -> list[dict] | None:
    """解析 LLM 输出的嵌套编号大纲；无法解析时返回 None。"""
    items: list[dict] = []
    for line in (text or "").splitlines():
        match = _NUMBERED_LINE.match(line.strip())
        if match:
            parts = match.group(1).split(".")
            level = min(len(parts), 2)
            title = _clean_title(match.group(2))
            if title and len(title) <= _MAX_TITLE_LENGTH:
                items.append({"level": level, "title": title})
    if not items:
        # Markdown 风格回退：## 一级 / ### 二级
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                title = _clean_title(stripped[4:])
                if title:
                    items.append({"level": 2, "title": title})
            elif stripped.startswith("## "):
                title = _clean_title(stripped[3:])
                if title:
                    items.append({"level": 1, "title": title})
    if not items:
        # 简单列表回退：- 一级 / 缩进二级
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith(("-", "*")):
                title = _clean_title(stripped.lstrip("-*# "))
                if title and len(title) <= _MAX_TITLE_LENGTH:
                    level = 2 if line.startswith(("  ", "\t")) else 1
                    items.append({"level": level, "title": title})
    return _assemble(items)


def fallback_structure(
    base_sections: list[str],
    template_hierarchy: list[dict] | None = None,
) -> list[dict]:
    """LLM 输出不可用时：以参考一级大纲为骨架，挂载模板二级标题。"""
    subs_by_title, _ = _template_subs_map(template_hierarchy)
    structure = [
        {"title": title, "subsections": list(subs_by_title.get(title, []))}
        for title in base_sections
    ]
    return structure


def enrich_subsections(
    structure: list[dict],
    template_hierarchy: list[dict] | None,
) -> list[dict]:
    """LLM 未给出二级标题时，用模板对应章节的二级标题补齐（按标题或位置匹配）。"""
    template_subs, template_level1 = _template_subs_map(template_hierarchy)

    enriched: list[dict] = []
    for index, item in enumerate(structure):
        title = item.get("title", "")
        subsections = _dedupe(item.get("subsections", []) or [])
        if not subsections:
            # 优先标题精确匹配，其次按位置回退
            subsections = list(template_subs.get(title) or [])
            if not subsections and index < len(template_level1):
                subsections = list(template_subs.get(template_level1[index]) or [])
        enriched.append(
            {"title": title, "subsections": subsections[:_MAX_SUBSECTIONS]}
        )
    return enriched


def _template_subs_map(
    template_hierarchy: list[dict] | None,
) -> tuple[dict[str, list[str]], list[str]]:
    """把模板层级拆为 {一级标题: [二级标题...]} 与一级标题顺序列表。"""
    subs_by_title: dict[str, list[str]] = {}
    for item in template_hierarchy or []:
        if item.get("level", 1) == 1:
            subs_by_title.setdefault(item.get("title", ""), [])
    current: str | None = None
    for item in template_hierarchy or []:
        title = item.get("title", "")
        if item.get("level", 1) == 1:
            current = title
        elif current is not None:
            subs_by_title.setdefault(current, []).append(title)
    return subs_by_title, list(subs_by_title.keys())


def _assemble(items: list[dict]) -> list[dict] | None:
    """把扁平层级项组装为 [{title, subsections}]；有效一级章节过少返回 None。"""
    structure: list[dict] = []
    current: dict | None = None
    for item in items:
        if item["level"] == 1:
            current = {"title": item["title"], "subsections": []}
            structure.append(current)
        elif item["level"] == 2 and current is not None:
            current["subsections"].append(item["title"])
        elif current is None:
            current = {"title": item["title"], "subsections": []}
            structure.append(current)
    structure = [
        {"title": item["title"], "subsections": _dedupe(item["subsections"])[:_MAX_SUBSECTIONS]}
        for item in structure
    ][:_MAX_SECTIONS]
    logger.info("真正使用的模板大钢：structure: %s", structure)
    return structure if len(structure) >= _MIN_SECTIONS else None


def _clean_title(title: str) -> str:
    """去除标题中的 Markdown 标记字符。"""
    return re.sub(r"[*_`#]", "", title).strip()


def _dedupe(items: list[str]) -> list[str]:
    """按顺序去重并过滤空串。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
