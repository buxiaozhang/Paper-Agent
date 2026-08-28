"""大纲提取工具：从 docx / pdf 模板中提取章节大纲（含一级 / 二级 / 三级层级）。

- docx：标题样式（Heading 1 / 2 / 3、标题 1 / 2 / 3、TOC 层级）与编号 / 关键词启发式
  合并提取；无样式时按编号（1. / 1.1 / 1.1.1 / 第X章）推断层级。缺失一级父章节时
  （如模板仅给二级标题加样式、章节名未加样式），按编号 / 邻近短标题行修复补回。
- pdf：优先读取书签层级；无书签时按文本编号启发式，并同样修复缺失的父章节。
- 未上传模板或提取为空时回退默认一级大纲。
解析库采用延迟导入，模板解析失败时调用方回退默认大纲。
"""

import re
from io import BytesIO
from pathlib import Path

# 软工实现
DEFAULT_SECTIONS = ["绪论", "相关技术", "系统分析", "功能需求分析", "系统设计","系统实现","系统测试","总结与展望","参考文献"]

_HEADING_STYLE_MARKERS = ("heading", "标题", "toc")
_MAX_HEADING_LENGTH = 60
_MAX_LEVEL = 3

# 编号前缀：1. / 1.1 / 1.1.1 或（1）（1.1）
_NUMBER_PREFIX = re.compile(r"^\s*[（(]?(\d+(?:\.\d+)*)[)）]?\s*[.、:：)）]?\s*")
_CHAPTER_PREFIX = re.compile(r"^第([一二三四五六七八九十百0-9]+)([章节])\s*[.、:：]?\s*")

# 无编号但明显属于一级章节的标题（精确匹配，避免误伤“测试总结”等二级标题）
_LEVEL1_KEYWORDS = {
    "绪论", "引言", "前言", "绪言", "结论", "总结", "展望", "总结与展望", "结论与展望",
    "参考文献", "致谢", "摘要", "目录", "附录",
    "相关技术", "相关技术介绍", "相关理论与技术", "关键技术", "技术选型", "技术栈", "技术介绍",
    "需求分析", "可行性分析", "系统分析",
    "系统设计", "总体设计", "概要设计", "详细设计", "系统架构设计", "系统总体架构设计",
    "系统实现", "功能实现", "系统实现与测试", "系统测试", "测试",
    "abstract", "references", "acknowledgements", "acknowledgment", "contents",
    "appendix", "introduction", "conclusion", "related work", "method", "methods",
    "experiments", "results", "discussion",
}
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


# ---------- 对外接口 ----------
def extract_outline(filename: str, content: bytes) -> list[str]:
    """提取一级章节大纲（扁平列表，保持旧接口语义）。"""
    structure = extract_outline_structure(filename, content)
    level1 = [item["title"] for item in structure if item["level"] == 1]
    if level1:
        return _dedupe(level1)
    return _dedupe([item["title"] for item in structure])


def extract_outline_structure(filename: str, content: bytes) -> list[dict]:
    """提取带层级的大纲：[{"level": 1|2|3, "title": ...}, ...]（按出现顺序）。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return extract_structure_from_pdf(content)
    return extract_structure_from_docx(content)


def extract_outline_from_docx(content: bytes) -> list[str]:
    """从 .docx 提取一级大纲（旧接口）。"""
    structure = extract_structure_from_docx(content)
    level1 = [item["title"] for item in structure if item["level"] == 1]
    return _dedupe(level1) if level1 else _dedupe([item["title"] for item in structure])


def extract_outline_from_pdf(content: bytes) -> list[str]:
    """从 .pdf 提取一级大纲（旧接口）。"""
    structure = extract_structure_from_pdf(content)
    level1 = [item["title"] for item in structure if item["level"] == 1]
    return _dedupe(level1) if level1 else _dedupe([item["title"] for item in structure])


# ---------- docx / pdf 层级提取 ----------
def extract_structure_from_docx(content: bytes) -> list[dict]:
    """按样式 + 编号 / 关键词合并提取层级，并修复缺失的一级父章节。"""
    from docx import Document

    document = Document(BytesIO(content))
    rows = [(p.style.name or "", (p.text or "").strip()) for p in document.paragraphs]
    items = _merge_candidates(rows)
    if not items:
        items = _short_line_fallback(rows)
    items = _repair_missing_parents(items, rows)
    return _finalize_structure(items)


def extract_structure_from_pdf(content: bytes) -> list[dict]:
    """优先按 PDF 书签层级提取；无书签时按正文启发式；书签缺父章节时用正文修复。"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    items = _collect_pdf_outline_structure(reader.outline, depth=1)
    if not items:
        items = _heuristic_structure(_pdf_text_lines(reader))
    else:
        rows = [("", line) for line in _pdf_text_lines(reader)]
        items = _repair_missing_parents(items, rows)
    return _finalize_structure(items)


# ---------- 层级工具 ----------
def split_structure(structure: list[dict]) -> tuple[list[str], dict[str, list[dict]]]:
    """把大纲拆分为（一级标题列表, {一级标题: 二级(含三级)嵌套列表}）。

    兼容两种输入：
    - 扁平层级：[{"level": 1|2|3, "title": ...}]（模板提取结果）
    - 嵌套结构：[{"title": ..., "subsections": [...]}]（OutlineAgent 输出）
    返回的 subsections 统一为 [{"title": 二级标题, "subsections": [三级标题...]}]。
    """
    sections: list[str] = []
    subsections: dict[str, list[dict]] = {}
    for item in structure or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        if "level" in item:
            level = min(int(item.get("level", 1)), _MAX_LEVEL)
            if level == 1:
                sections.append(title)
                subsections.setdefault(title, [])
            elif level == 2 and sections:
                subsections.setdefault(sections[-1], []).append(
                    {"title": title, "subsections": []}
                )
            elif level == 3 and sections:
                parent = subsections.setdefault(sections[-1], [])
                if parent:
                    parent[-1].setdefault("subsections", []).append(title)
                else:
                    parent.append({"title": title, "subsections": []})
        else:
            # 嵌套结构（OutlineAgent 输出）
            sections.append(title)
            subsections[title] = normalize_subsections(item.get("subsections"))
    return sections, subsections


def hierarchy_to_text(hierarchy: list[dict] | None) -> str:
    """层级大纲 -> 缩进文本（供 LLM 提示词使用，支持到三级标题）。"""
    lines: list[str] = []
    section_no = 0
    sub_no = 0
    subsub_no = 0
    for item in hierarchy or []:
        title = item.get("title", "")
        if not title:
            continue
        level = min(int(item.get("level", 1)), _MAX_LEVEL)
        if level == 1:
            section_no += 1
            sub_no = 0
            subsub_no = 0
            lines.append(f"{section_no}. {title}")
        elif level == 2:
            sub_no += 1
            subsub_no = 0
            lines.append(f"  {section_no}.{sub_no} {title}")
        else:
            subsub_no += 1
            lines.append(f"    {section_no}.{sub_no}.{subsub_no} {title}")
    return "\n".join(lines)


def normalize_subsections(subsections) -> list[dict]:
    """把二级标题统一为嵌套结构 [{"title":..., "subsections":[...]}]，兼容旧 list[str]。"""
    result: list[dict] = []
    for item in subsections or []:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append({"title": text, "subsections": []})
        elif isinstance(item, dict):
            text = (item.get("title") or "").strip()
            if not text:
                continue
            children = [
                s.strip()
                for s in item.get("subsections") or []
                if isinstance(s, str) and s.strip()
            ]
            result.append({"title": text, "subsections": children})
    return result


def flatten_subsection_titles(subsections) -> list[str]:
    """把嵌套二级标题展平为标题列表（二级在前、三级在后），用于检索关键词。"""
    titles: list[str] = []
    for item in normalize_subsections(subsections):
        titles.append(item["title"])
        titles.extend(item["subsections"])
    return titles


def render_subsections(section_no: int, subsections) -> list[str]:
    """把嵌套二级标题渲染为带编号的文本行，供写作提示使用。"""
    lines: list[str] = []
    for i, item in enumerate(normalize_subsections(subsections), 1):
        lines.append(f"{section_no}.{i} {item['title']}")
        for j, sub in enumerate(item["subsections"], 1):
            lines.append(f"  {section_no}.{i}.{j} {sub}")
    return lines


def resolve_sections(template_outline: list[str] | None) -> list[str]:
    """优先使用模板提取的大纲；未提供或提取为空时回退默认大纲。"""
    sections = _dedupe(template_outline or [])
    return sections or DEFAULT_SECTIONS


# ---------- 内部实现 ----------
def _style_level(style_name: str) -> int | None:
    """从样式名推断层级：Heading 1 / 标题 1 / TOC 1 -> 1，以此类推。"""
    match = re.search(r"(heading|标题|toc)\s*(\d+)", style_name)
    if match:
        return min(int(match.group(2)), _MAX_LEVEL)
    if any(marker in style_name for marker in _HEADING_STYLE_MARKERS):
        return 1
    return None


def _detect_level(text: str) -> int | None:
    """按编号前缀推断层级：1. -> 1；1.1 -> 2；1.1.1 -> 3；第X章 -> 1；第X节 -> 2。"""
    match = _NUMBER_PREFIX.match(text)
    if match:
        return min(len(match.group(1).split(".")), _MAX_LEVEL)
    chapter = _CHAPTER_PREFIX.match(text)
    if chapter:
        return 1 if chapter.group(2) == "章" else 2
    if text[0].isdigit() or text.startswith(("第", "一", "二", "三", "四", "五")):
        return 1
    return None


def _heuristic_structure(lines) -> list[dict]:
    """无样式 / 无书签时的层级启发式：编号 / 关键词优先，最后回退短标题行。"""
    rows = [("", str(line).strip()) for line in lines]
    items = _merge_candidates(rows)
    if not items:
        items = _short_line_fallback(rows)
    items = _repair_missing_parents(items, rows)
    return _finalize_structure(items)


def _merge_candidates(rows) -> list[dict]:
    """合并样式 / 编号 / 关键词三种信号，返回按文档顺序的候选层级项（保留原始标题）。

    rows: [(style_name, text), ...]。样式优先级最高；无样式时依次尝试
    编号前缀（带标题尾部校验）与一级章节关键词，避免把正文行误当标题。
    """
    items: list[dict] = []
    for index, (style_name, text) in enumerate(rows):
        if not text or len(text) > _MAX_HEADING_LENGTH:
            continue
        level = _style_level((style_name or "").lower())
        if level is None:
            detected = _detect_level(text)
            if detected is not None and _numbered_tail_looks_like_title(text):
                level = detected
            elif _keyword_level(text) is not None:
                level = _keyword_level(text)
        if level:
            items.append({"level": min(level, _MAX_LEVEL), "title": text, "_index": index})
    return items


def _short_line_fallback(rows) -> list[dict]:
    """没有任何编号 / 样式信号时，回退为英文短标题行启发式。"""
    items: list[dict] = []
    for index, (_, text) in enumerate(rows):
        if _looks_like_heading(text):
            items.append(
                {"level": 1, "title": _strip_number_prefix(text), "_index": index}
            )
    return items


def _repair_missing_parents(items: list[dict], rows) -> list[dict]:
    """为缺少一级父章节的二级标题补插父章节，避免挂到上一个无关章节下。

    优先从原文行中恢复父章节文本（相同章编号 / 关键词 / 邻近短标题行）；
    找不到时插入“第N章”占位，保证章节边界正确。无编号的一级标题（如
    “相关技术介绍”“参考文献”）直接吸收其后同编号序列的二级标题，不再重复补插。
    """
    consumed: set[int] = {
        item["_index"] for item in items if item.get("_index") is not None
    }
    fixed: list[dict] = []
    current_chapter: int | None = None
    last_parent_unnumbered: bool = False
    unnumbered_run_chapter: int | None = None
    last_parent_index: int = -1
    for item in items:
        if item["level"] == 1:
            number = _leading_chapter_number(item["title"])
            if number is not None:
                current_chapter = number
                last_parent_unnumbered = False
            else:
                last_parent_unnumbered = True
            unnumbered_run_chapter = None
            last_parent_index = item.get("_index", -1)
            fixed.append(item)
            continue
        chapter_no = _leading_chapter_number(item["title"])
        if last_parent_unnumbered:
            if unnumbered_run_chapter is None or chapter_no is None:
                unnumbered_run_chapter = chapter_no
                fixed.append(item)
                continue
            if chapter_no == unnumbered_run_chapter:
                fixed.append(item)
                continue
            # 同一无编号父章节下出现新的章编号序列，视为又缺失一级父章节
        elif chapter_no is None or chapter_no == current_chapter:
            fixed.append(item)
            continue
        parent_text, parent_index = _find_parent_line(
            rows, consumed, chapter_no, last_parent_index, item.get("_index", -1)
        )
        if parent_text is not None:
            consumed.add(parent_index)
            fixed.append({"level": 1, "title": parent_text, "_index": parent_index})
            last_parent_index = parent_index
        else:
            fixed.append({"level": 1, "title": f"第{chapter_no}章", "_index": -1})
            last_parent_index = -1
        current_chapter = chapter_no
        last_parent_unnumbered = False
        unnumbered_run_chapter = None
        fixed.append(item)
    return fixed


def _find_parent_line(
    rows,
    consumed: set[int],
    chapter_no: int,
    start: int,
    end: int,
) -> tuple[str | None, int]:
    """在指定区间内寻找缺失父章节的原文行：编号一致 > 关键词 > 邻近短标题行。"""
    lo = max(start + 1, 0)
    hi = end if end >= 0 else len(rows)
    short_candidates: list[tuple[int, str]] = []
    for index in range(lo, min(hi, len(rows))):
        if index in consumed:
            continue
        _, text = rows[index]
        if not text or len(text) > _MAX_HEADING_LENGTH:
            continue
        if _detect_level(text) == 1 and _leading_chapter_number(text) == chapter_no:
            return text, index
        if _keyword_level(text) == 1:
            return text, index
        if _looks_like_unnumbered_title(text):
            short_candidates.append((index, text))
    if short_candidates:
        # 优先离二级标题最近的短标题行（章节名通常紧跟第一个二级标题之前）
        index, text = max(short_candidates, key=lambda pair: pair[0])
        return text, index
    return None, -1


def _finalize_structure(items: list[dict]) -> list[dict]:
    """清理层级项：去除编号前缀（去除后为空则保留原文），按 (层级, 标题) 去重。"""
    deduped = _dedupe_structure(items)
    cleaned: list[dict] = []
    for item in deduped:
        raw = (item.get("title") or "").strip()
        title = _strip_number_prefix(raw) or raw
        cleaned.append({"level": min(int(item.get("level", 1)), _MAX_LEVEL), "title": title})
    return cleaned


def _keyword_level(text: str) -> int | None:
    """无编号的常见一级章节关键词（参考文献 / 致谢 / 摘要等）视为一级标题。"""
    if _strip_number_prefix(text) in _LEVEL1_KEYWORDS:
        return 1
    return None


def _numbered_tail_looks_like_title(text: str) -> bool:
    """编号后的标题部分是否像标题：短、无句末标点，中文短语或英文单词首字母大写。"""
    tail = _strip_number_prefix(text)
    if not tail or len(tail) > 40:
        return False
    if tail[-1] in "。，；：、,.;:?？!！)）":
        return False
    if re.search(r"[\u4e00-\u9fff]", tail):
        return len(tail) >= 4 or tail in _LEVEL1_KEYWORDS
    words = tail.split()
    return bool(words) and len(words) <= 10 and all(
        not (len(word) > 3 and word[0].islower()) for word in words
    )


def _looks_like_unnumbered_title(text: str) -> bool:
    """判断无编号行是否像一级章节标题（用于缺失父章节的短标题行修复）。"""
    if len(text) < 2 or len(text) > 30:
        return False
    if text[-1] in "。，；：、,.;:?？!！":
        return False
    if _detect_level(text):
        return False
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()·\- ]+", text):
        return True
    words = text.split()
    return bool(words) and len(words) <= 10 and all(
        not (len(word) > 3 and word[0].islower()) for word in words
    )


def _leading_chapter_number(text: str) -> int | None:
    """提取标题首部的章编号：'1 绪论' -> 1；'2.1 Java Web' -> 2；'第3章 ...' -> 3。"""
    match = _NUMBER_PREFIX.match(text)
    if match:
        return int(match.group(1).split(".")[0])
    chapter = _CHAPTER_PREFIX.match(text)
    if chapter:
        return _cn_to_int(chapter.group(1))
    return None


def _cn_to_int(cn: str) -> int:
    """中文数字转整数：'二' -> 2，'十二' -> 12，'二十' -> 20。"""
    if cn.isdigit():
        return int(cn)
    total, section = 0, 0
    for char in cn:
        digit = _CN_DIGITS.get(char)
        if digit is None:
            continue
        if digit == 10:
            total += (section or 1) * 10
            section = 0
        else:
            section = digit
    return total + section


def _pdf_text_lines(reader, max_pages: int = 12) -> list[str]:
    """提取 PDF 前若干页的正文行。"""
    lines: list[str] = []
    for page in reader.pages[:max_pages]:
        lines.extend((page.extract_text() or "").splitlines())
    return lines


def _strip_number_prefix(text: str) -> str:
    """去掉标题前的编号前缀（1. / 1.1 / 第X章）。"""
    text = _NUMBER_PREFIX.sub("", text.strip())
    text = _CHAPTER_PREFIX.sub("", text)
    return re.sub(r"[*_`#]", "", text).strip()


def _collect_pdf_outline_structure(items, depth: int = 1) -> list[dict]:
    """递归收集 PDF 书签层级（深度超过 2 统一视为 2 级）。"""
    structure: list[dict] = []
    for item in items or []:
        if isinstance(item, (list, tuple)):
            structure.extend(_collect_pdf_outline_structure(item, depth))
            continue
        title = getattr(item, "title", None)
        if title:
            structure.append({"level": min(depth, _MAX_LEVEL), "title": str(title).strip()})
        children = getattr(item, "children", None) or getattr(item, "subitems", None)
        if children:
            structure.extend(_collect_pdf_outline_structure(children, depth + 1))
    return structure


def _collect_pdf_outline(items) -> list[str]:
    """递归收集 PDF 书签标题（扁平，旧接口使用）。"""
    headings: list[str] = []
    for item in items or []:
        if isinstance(item, (list, tuple)):
            headings.extend(_collect_pdf_outline(item))
            continue
        title = getattr(item, "title", None)
        if title:
            headings.append(str(title).strip())
        children = getattr(item, "children", None) or getattr(item, "subitems", None)
        if children:
            headings.extend(_collect_pdf_outline(children))
    return headings


def _heading_candidates(lines) -> list[str]:
    """启发式筛选（旧接口使用）：编号开头或较短的英文标题行。"""
    candidates = []
    for line in lines:
        text = line.strip()
        if _looks_like_heading(text):
            candidates.append(text)
    return _dedupe(candidates)


def _looks_like_heading(text: str) -> bool:
    """判断一行文本是否像章节标题。"""
    if not text or len(text) > _MAX_HEADING_LENGTH:
        return False
    if _detect_level(text):
        return True
    words = text.split()
    if not words or len(words) > 10:
        return False
    if not words[0][0].isupper() or text.endswith((".", "。", ";", "；", ",", "，")):
        return False
    # 英文标题近似判定：长单词应首字母大写，排除普通陈述句（如 "In this paper..."）
    return all(not (len(word) > 3 and word[0].islower()) for word in words)


def _dedupe_structure(items: list[dict]) -> list[dict]:
    """按 (level, title) 去重，过滤空标题。"""
    seen: set[tuple[int, str]] = set()
    result: list[dict] = []
    for item in items:
        title = (item.get("title") or "").strip()
        level = min(int(item.get("level", 1)), _MAX_LEVEL)
        if title and (level, title) not in seen:
            seen.add((level, title))
            result.append({"level": level, "title": title})
    return result


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
