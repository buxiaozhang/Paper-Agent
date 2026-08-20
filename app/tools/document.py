"""文档解析 / 生成工具：python-docx 与 docxtpl。"""

from io import BytesIO

from docx import Document
from docxtpl import DocxTemplate


def extract_text_from_docx(content: bytes) -> str:
    """解析 .docx 文件并提取纯文本。"""
    document = Document(BytesIO(content))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def render_docx_template(template_path: str, context: dict, output_path: str) -> None:
    """使用 docxtpl 渲染 Word 模板。

    Args:
        template_path: 带 Jinja2 占位符的 .docx 模板路径。
        context: 渲染上下文（论文标题、章节、图表等）。
        output_path: 输出文件路径。
    """
    template = DocxTemplate(template_path)
    template.render(context)
    template.save(output_path)


def build_paper_docx(title: str, sections: dict[str, str], output_path: str) -> None:
    """根据论文标题与章节正文生成 .docx 文档。"""
    document = Document()
    document.add_heading(title, level=0)
    for heading, body in sections.items():
        document.add_heading(heading, level=1)
        document.add_paragraph(body)
    document.save(output_path)
