"""大纲提取工具：从 docx / pdf 模板中提取章节大纲。

流水线的大纲优先级：上传模板提取的大纲 -> 默认大纲（未上传模板时）。
docx 使用 python-docx 按标题样式提取；pdf 优先读取书签，无书签时按
文本启发式提取。解析库采用延迟导入，模板解析失败时调用方回退默认大纲。
"""

from io import BytesIO
from pathlib import Path

DEFAULT_SECTIONS = ["引言", "相关工作", "方法", "实验与结果", "结论"]

_HEADING_STYLE_MARKERS = ("heading", "标题", "toc")
_MAX_HEADING_LENGTH = 60


def extract_outline(filename: str, content: bytes) -> list[str]:
    """按文件扩展名分发到 docx / pdf 提取器，返回章节大纲列表。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return extract_outline_from_pdf(content)
    return extract_outline_from_docx(content)  # .docx 及默认按 docx 解析


def extract_outline_from_docx(content: bytes) -> list[str]:
    """从 .docx 模板提取大纲：优先标题样式，无标题样式时按文本启发式。"""
    from docx import Document

    document = Document(BytesIO(content))
    headings = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (paragraph.style.name or "").lower()
        if any(marker in style_name for marker in _HEADING_STYLE_MARKERS):
            headings.append(text)
    if not headings:
        headings = _heading_candidates(p.text for p in document.paragraphs)
    return _dedupe(headings)


def extract_outline_from_pdf(content: bytes) -> list[str]:
    """从 .pdf 模板提取大纲：优先 PDF 书签，无书签时按文本启发式。"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    headings = _collect_pdf_outline(reader.outline)
    if not headings:
        candidates: list[str] = []
        for page in reader.pages[:12]:
            candidates.extend((page.extract_text() or "").splitlines())
        headings = _heading_candidates(candidates)
    return _dedupe(headings)


def resolve_sections(template_outline: list[str] | None) -> list[str]:
    """优先使用模板提取的大纲；未提供或提取为空时回退默认大纲。"""
    sections = _dedupe(template_outline or [])
    return sections or DEFAULT_SECTIONS


def _collect_pdf_outline(items) -> list[str]:
    """递归收集 PDF 书签（OutlineItem）标题。"""
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
    """启发式筛选：编号开头（1. / 第一章）或较短的英文标题行。"""
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
    if text[0].isdigit() or text.startswith(("第", "一", "二", "三", "四", "五")):
        return True
    words = text.split()
    if not words or len(words) > 10:
        return False
    if not words[0][0].isupper() or text.endswith((".", "。", ";", "；", ",", "，")):
        return False
    # 英文标题近似判定：长单词应首字母大写，排除普通陈述句（如 "In this paper..."）
    return all(not (len(word) > 3 and word[0].islower()) for word in words)


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
