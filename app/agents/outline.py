"""大纲 Agent：基于论文主题与参考大纲，生成专属层级大纲（一级 + 二级 + 三级标题）。"""

import logging
import re

from app.agents.base import BaseAgent
from app.tools.outline import hierarchy_to_text, normalize_subsections

logger = logging.getLogger(__name__)

_NUMBERED_LINE = re.compile(
    r"^\s*[（(]?(\d+(?:\.\d+)*)[)）]?\s*[.、:：)）]?\s*(.+?)\s*$"
)
_MAX_SECTIONS = 12
_MIN_SECTIONS = 2
_MAX_TITLE_LENGTH = 40
# 仅约束“无模板可依”时 LLM 自行生成的二级标题数量；模板已有的二级标题完整保留。
_MAX_SUBSECTIONS = 6


class OutlineAgent(BaseAgent):
    """大纲生成与优化 Agent：生成紧扣主题的一级大纲，并给出二级 / 三级标题。"""

    name = "outliner"
    description = "大纲生成与优化 Agent"

    def run(
        self,
        topic: str,
        base_sections: list[str],
        references: list[dict] | None = None,
        template_hierarchy: list[dict] | None = None,
    ) -> list[dict]:
        """生成专属层级大纲。

        返回嵌套结构：
        [{"title": 一级标题, "subsections": [
            {"title": 二级标题, "subsections": [三级标题...]}, ...]}, ...]

        Args:
            template_hierarchy: 模板的完整层级（一级 + 二级 + 三级），作为下级标题的参考；
                未提供时仅按主题与一级参考大纲生成。
        """
        base_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(base_sections))
        logger.info("模板大纲：%s",base_text)
        template_text = hierarchy_to_text(template_hierarchy)
        prompt = (
            "你是学术论文写作专家。请根据论文主题和参考大纲，生成一份专属于该论文的章节大纲，"
            "包含一级标题、每个一级标题下的二级标题，以及必要的三级标题。\n"
            f"论文主题：{topic}\n"
            f"参考大纲（可能来自论文模板或默认结构）：\n{base_text}\n"
        )
        if template_text:
            prompt += (
                f"模板的完整层级结构（模板的二级、三级标题为硬性参考，必须尽量沿用）：\n"
                f"{template_text}\n"
            )
        prompt += (
            "要求：\n"
            "1. 一级标题紧扣主题（可参考模板一级标题），删除与主题无关的章节；\n"
            "2. 二级、三级标题必须严格对齐模板：模板中已有的章节，直接沿用其二级及三级标题"
            "（如主题确有需要，仅允许在末尾追加个别主题专属标题，不得改写、删减"
            "或调换模板已有标题）；只有模板中没有的全新章节才自行拟定下级标题；\n"
            "3. 章节数量适中（一级标题建议 5-10 个）；\n"
            "4. 每行一个标题，用编号层级表示级别，例如：\n"
            "1. 引言\n1.1 研究背景\n1.2 研究意义\n2. 系统分析\n2.1 可行性分析\n"
            "2.1.1 技术可行性\n2.1.2 经济可行性\n"
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
        level2_count = sum(len(item.get("subsections", [])) for item in structure)
        level3_count = sum(
            len(sub.get("subsections", []))
            for item in structure
            for sub in item.get("subsections", [])
        )
        logger.info(
            "大纲优化完成：%d 个一级章节，二级标题 %d 个，三级标题 %d 个",
            len(structure),
            level2_count,
            level3_count,
        )

        return structure


def parse_structure(text: str) -> list[dict] | None:
    """解析 LLM 输出的嵌套编号大纲；无法解析时返回 None。"""
    items: list[dict] = []
    for line in (text or "").splitlines():
        match = _NUMBERED_LINE.match(line.strip())
        if match:
            parts = match.group(1).split(".")
            level = min(len(parts), 3)
            title = _clean_title(match.group(2))
            if title and len(title) <= _MAX_TITLE_LENGTH:
                items.append({"level": level, "title": title})
    if not items:
        # Markdown 风格回退：## 一级 / ### 二级 / #### 三级
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#### "):
                title = _clean_title(stripped[5:])
                if title:
                    items.append({"level": 3, "title": title})
            elif stripped.startswith("### "):
                title = _clean_title(stripped[4:])
                if title:
                    items.append({"level": 2, "title": title})
            elif stripped.startswith("## "):
                title = _clean_title(stripped[3:])
                if title:
                    items.append({"level": 1, "title": title})
    if not items:
        # 简单列表回退：- 一级 / 缩进二级 / 再缩进三级
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith(("-", "*")):
                title = _clean_title(stripped.lstrip("-*# "))
                if title and len(title) <= _MAX_TITLE_LENGTH:
                    indent = len(line) - len(line.lstrip())
                    level = 3 if indent >= 4 else (2 if indent >= 2 else 1)
                    items.append({"level": level, "title": title})
    return _assemble(items)


def fallback_structure(
    base_sections: list[str],
    template_hierarchy: list[dict] | None = None,
) -> list[dict]:
    """LLM 输出不可用时：以参考一级大纲为骨架，挂载模板对应章节的二级 / 三级标题。"""
    subs_by_title, template_level1 = _template_nested_map(template_hierarchy)
    structure = []
    for title in base_sections:
        matched = _match_template_section(title, template_level1)
        subsections = list(subs_by_title.get(matched, [])) if matched else []
        structure.append({"title": title, "subsections": subsections})
    return structure


def enrich_subsections(
    structure: list[dict],
    template_hierarchy: list[dict] | None,
) -> list[dict]:
    """对齐并补齐二级 / 三级标题：模板已有章节优先沿用模板层级，仅追加主题专属标题。

    与旧实现不同，这里不仅兜底补齐“缺下级标题”的章节，还会在 LLM 已生成下级标题时
    用模板层级覆盖/前置，避免大纲 Agent 自行发挥导致与模板差异过大。
    """
    template_subs, template_level1 = _template_nested_map(template_hierarchy)

    enriched: list[dict] = []
    for index, item in enumerate(structure):
        title = item.get("title", "")
        generated = normalize_subsections(item.get("subsections", []))
        matched = _match_template_section(title, template_level1)
        template_for_title = template_subs.get(matched) if matched else None
        if template_for_title:
            # 模板二级/三级标题完整保留（不截断），主题专属标题去重后追加
            subsections = _merge_subsections(template_for_title, generated)
        elif not generated and index < len(template_level1):
            # 标题未匹配但无下级标题时，按位置兜底补齐（模板层级完整保留）
            subsections = list(template_subs.get(template_level1[index], []))
        else:
            # 无模板可依时，仅对 LLM 自行生成的下级标题做数量上限
            subsections = _cap_subsections(generated)
        enriched.append({"title": title, "subsections": subsections})
    return enriched


def _merge_subsections(
    template_subsections: list[dict],
    generated_subsections: list[dict],
) -> list[dict]:
    """合并模板与 LLM 生成的二级标题：模板优先，主题专属的新二级/三级标题去重追加。"""
    result: list[dict] = []
    for template_item in template_subsections:
        template_title = template_item["title"]
        template_children = list(template_item.get("subsections", []))
        gen_match = _find_l2(template_title, generated_subsections)
        gen_children = gen_match.get("subsections", []) if gen_match else []
        children = _dedupe(template_children)
        for sub in gen_children:
            if not _is_duplicate_subsection(sub, children):
                children.append(sub)
        result.append({"title": template_title, "subsections": children})
    for gen_item in generated_subsections:
        if not any(
            _normalize_title(gen_item["title"]) == _normalize_title(t["title"])
            for t in template_subsections
        ):
            result.append(gen_item)
    return result


def _find_l2(title: str, generated_subsections: list[dict]) -> dict | None:
    """按标题精确匹配生成的二级标题项。"""
    norm = _normalize_title(title)
    for item in generated_subsections:
        if _normalize_title(item.get("title", "")) == norm:
            return item
    return None


def _cap_subsections(
    subsections: list[dict],
    max_l2: int = _MAX_SUBSECTIONS,
    max_l3: int = _MAX_SUBSECTIONS,
) -> list[dict]:
    """对 LLM 自行生成的二级 / 三级标题做数量上限。"""
    capped: list[dict] = []
    for item in subsections[:max_l2]:
        capped.append(
            {
                "title": item["title"],
                "subsections": _dedupe(item.get("subsections", []))[:max_l3],
            }
        )
    return capped


def _match_template_section(title: str, template_level1: list[str]) -> str | None:
    """返回与生成章节标题匹配的模板一级标题（精确优先，其次包含关系）；无匹配返回 None。"""
    norm_title = _normalize_title(title)
    if not norm_title or not template_level1:
        return None
    for template_title in template_level1:
        if _normalize_title(template_title) == norm_title:
            return template_title
    for template_title in template_level1:
        norm_template = _normalize_title(template_title)
        if norm_template and (norm_template in norm_title or norm_title in norm_template):
            return template_title
    return None


def _normalize_title(title: str) -> str:
    """归一化章节标题用于匹配：去空白与常见中英文标点。"""
    return re.sub(r"[\s:：、，,。.；;（）()【】\[\]《》<>]+", "", title or "")


def _is_duplicate_subsection(candidate: str, existing: list[str]) -> bool:
    """判断候选二级标题是否与已有标题重复（精确相等或互为子串）。"""
    norm_candidate = _normalize_title(candidate)
    if not norm_candidate:
        return True
    for title in existing:
        norm_title = _normalize_title(title)
        if norm_title and (
            norm_candidate == norm_title
            or norm_candidate in norm_title
            or norm_title in norm_candidate
        ):
            return True
    return False


def _template_nested_map(
    template_hierarchy: list[dict] | None,
) -> tuple[dict[str, list[dict]], list[str]]:
    """把模板层级拆为 {一级标题: [{"title": 二级, "subsections": [三级...]}]} 与一级顺序。"""
    subs_by_title: dict[str, list[dict]] = {}
    current_l1: str | None = None
    current_l2: dict | None = None
    for item in template_hierarchy or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        level = min(int(item.get("level", 1)), 3)
        if level == 1:
            current_l1 = title
            current_l2 = None
            subs_by_title.setdefault(title, [])
        elif level == 2:
            if current_l1 is None:
                continue
            current_l2 = {"title": title, "subsections": []}
            subs_by_title[current_l1].append(current_l2)
        elif current_l1 is not None:
            # 三级标题；若无二级父项则兜底作为二级标题项
            if current_l2 is None:
                current_l2 = {"title": title, "subsections": []}
                subs_by_title[current_l1].append(current_l2)
            else:
                current_l2.setdefault("subsections", []).append(title)
    return subs_by_title, list(subs_by_title.keys())


def _assemble(items: list[dict]) -> list[dict] | None:
    """把扁平层级项组装为三级嵌套结构；有效一级章节过少返回 None。

    输出：[{"title": 一级, "subsections": [{"title": 二级, "subsections": [三级...]}]}]
    """
    structure: list[dict] = []
    current_l1: dict | None = None
    current_l2: dict | None = None
    for item in items:
        level = item["level"]
        title = item["title"]
        if level == 1:
            current_l1 = {"title": title, "subsections": []}
            structure.append(current_l1)
            current_l2 = None
        elif level == 2:
            if current_l1 is None:
                current_l1 = {"title": title, "subsections": []}
                structure.append(current_l1)
                current_l2 = None
            else:
                current_l2 = {"title": title, "subsections": []}
                current_l1["subsections"].append(current_l2)
        else:  # 三级标题
            if current_l1 is None:
                current_l1 = {"title": title, "subsections": []}
                structure.append(current_l1)
                current_l2 = None
            elif current_l2 is None:
                current_l2 = {"title": title, "subsections": []}
                current_l1["subsections"].append(current_l2)
            else:
                current_l2.setdefault("subsections", []).append(title)
    # 去重（二级按标题、三级按标题）；不截断模板标题，数量上限交给 enrich_subsections。
    structure = [
        {
            "title": item["title"],
            "subsections": _dedupe_l2(item["subsections"]),
        }
        for item in structure
    ][:_MAX_SECTIONS]
    return structure if len(structure) >= _MIN_SECTIONS else None


def _dedupe_l2(subsections: list[dict]) -> list[dict]:
    """二级标题项按标题去重，并对其三级标题去重。"""
    seen: set[str] = set()
    result: list[dict] = []
    for item in subsections:
        title = (item.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(
            {"title": title, "subsections": _dedupe(item.get("subsections", []))}
        )
    return result


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
