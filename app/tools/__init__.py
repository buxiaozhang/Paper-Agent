"""外部工具包：文献检索、图片生成、文档解析。"""

from app.tools.document import build_paper_docx, extract_text_from_docx, render_docx_template
from app.tools.image_generation import WanxImageTool
from app.tools.literature import LiteratureSearchTool, PaperReference

__all__ = [
    "LiteratureSearchTool",
    "PaperReference",
    "WanxImageTool",
    "extract_text_from_docx",
    "render_docx_template",
    "build_paper_docx",
]
