"""外部工具包：文献检索、图片生成、文档解析。"""

from app.tools.document import build_paper_docx, extract_text_from_docx, render_docx_template
from app.tools.image_generation import WanxImageTool
from app.tools.literature import LiteratureSearchTool, PaperReference
from app.tools.outline import (
    DEFAULT_SECTIONS,
    extract_outline,
    extract_outline_from_docx,
    extract_outline_from_pdf,
    extract_outline_structure,
    flatten_subsection_titles,
    hierarchy_to_text,
    normalize_subsections,
    render_subsections,
    resolve_sections,
    split_structure,
)
from app.tools.template_index import TemplateIndex, TemplateIndexResult, chunk_template

__all__ = [
    "LiteratureSearchTool",
    "PaperReference",
    "WanxImageTool",
    "DEFAULT_SECTIONS",
    "extract_outline",
    "extract_outline_from_docx",
    "extract_outline_from_pdf",
    "extract_outline_structure",
    "hierarchy_to_text",
    "normalize_subsections",
    "flatten_subsection_titles",
    "render_subsections",
    "resolve_sections",
    "split_structure",
    "extract_text_from_docx",
    "render_docx_template",
    "build_paper_docx",
    "TemplateIndex",
    "TemplateIndexResult",
    "chunk_template",
]
