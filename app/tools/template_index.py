"""模板切片向量化与检索：上传模板时切片写入 Chroma，写作时按章节检索写法参考。

- docx：按段落样式 / 编号识别一级、二级标题，把每个小节正文切为独立片段；
- pdf：按正文行提取，同样识别编号标题，超长内容按固定大小切分并保留重叠；
- markdown（README.md 等）：按 #/##/### 标题层级切分正文；
- 索引以模板内容哈希为 template_id 去重，重新上传同一模板会先清理旧切片。
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app.config import settings
from app.tools.outline import (
    _detect_level,
    _numbered_tail_looks_like_title,
    _strip_number_prefix,
    _style_level,
)

logger = logging.getLogger(__name__)

_MAX_HEADING_LENGTH = 60


@dataclass
class TemplateIndexResult:
    """模板索引结果：模板唯一 ID 与切片数量。"""

    template_id: str
    chunk_count: int


class TemplateIndex:
    """模板 RAG 索引：把上传的范文模板切片向量化，供写作阶段检索写法参考。"""

    def __init__(self) -> None:
        self._memory = None  # 延迟初始化：无向量库环境不影响流水线主体

    @property
    def memory(self):
        if self._memory is None:
            from app.memory.long_term import LongTermMemory

            self._memory = LongTermMemory()
        return self._memory

    def index_template(
        self,
        filename: str,
        content: bytes,
        user_id: str = "default",
    ) -> TemplateIndexResult:
        """切片并向量化模板，返回 template_id（重传同一模板时先清理旧切片）。"""
        template_id = hashlib.sha256(
            f"{filename}\0".encode("utf-8") + content
        ).hexdigest()[:16]
        chunks = chunk_template(filename, content)
        if not chunks:
            logger.warning("模板 %s 未切分出可索引的正文内容", filename)
            return TemplateIndexResult(template_id, 0)

        texts: list[str] = []
        metadatas: list[dict] = []
        for chunk in chunks:
            prefix = chunk["level1"]
            if chunk.get("level2"):
                prefix = f"{prefix} / {chunk['level2']}" if prefix else chunk["level2"]
            texts.append(f"{prefix}\n{chunk['text']}" if prefix else chunk["text"])
            metadatas.append(
                {
                    "template_id": template_id,
                    "user_id": user_id,
                    "source": filename,
                    "level1": chunk["level1"],
                    "level2": chunk.get("level2", ""),
                    "chunk_index": chunk["chunk_index"],
                }
            )
        try:
            self.memory.delete_by_metadata({"template_id": template_id})
            self.memory.add_texts(texts, metadatas)
        except Exception:
            logger.exception("模板向量化写入失败（模板：%s）", filename)
            raise
        logger.info(
            "模板 %s 已切片向量化：%d 个片段写入 Chroma（template_id=%s）",
            filename,
            len(chunks),
            template_id,
        )
        return TemplateIndexResult(template_id, len(chunks))

    def search(self, template_id: str, query: str, top_k: int | None = None) -> list[str]:
        """检索模板中与查询最相似的片段文本；向量库不可用时静默返回空列表。"""
        try:
            results = self.memory.search(
                query,
                top_k=top_k or settings.template_top_k,
                where={"template_id": template_id},
            )
            return [text for text, _ in results]
        except Exception:
            logger.warning(
                "模板写法检索失败（template_id=%s），本次写作跳过模板参考",
                template_id,
                exc_info=True,
            )
            return []


# ---------- 切片实现 ----------
_MD_HEADING = re.compile(r"^(#{1,6})\s*(.*)$")


def chunk_template(filename: str, content: bytes) -> list[dict]:
    """把模板正文按标题结构切分为 [{text, level1, level2, chunk_index}]。

    支持 docx / pdf / markdown（README 等）；markdown 按 #/##/### 标题层级切分。
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return _chunks_from_rows([("", line.strip()) for line in _pdf_lines(content)])
    if suffix in (".md", ".markdown"):
        return _chunks_from_rows(_markdown_rows(content))
    return _chunks_from_rows(_docx_rows(content))


def _markdown_rows(content: bytes) -> list[tuple[str, str]]:
    """把 Markdown 文本按标题/正文行拆为 (样式, 文本) 行，复用统一切分逻辑。"""
    text = content.decode("utf-8", errors="ignore")
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _MD_HEADING.match(stripped)
        if match:
            level = min(len(match.group(1)), 3)
            body = match.group(2).strip()
            if body:
                rows.append((f"Heading {level}", body))
        else:
            rows.append(("", stripped))
    return rows


def _docx_rows(content: bytes) -> list[tuple[str, str]]:
    """提取 docx 段落（样式名, 文本）。"""
    from docx import Document

    document = Document(BytesIO(content))
    return [(p.style.name or "", (p.text or "").strip()) for p in document.paragraphs]


def _pdf_lines(content: bytes) -> list[str]:
    """提取 PDF 正文行。"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    lines: list[str] = []
    for page in reader.pages:
        lines.extend((page.extract_text() or "").splitlines())
    return lines


def _chunks_from_rows(rows: list[tuple[str, str]]) -> list[dict]:
    """按标题层级切分正文：每个小节独立成片段，超长内容按固定大小切分并保留重叠。"""
    chunks: list[dict] = []
    level1, level2 = "", ""
    buffer: list[str] = []
    chunk_index = 0

    def emit(text: str) -> None:
        nonlocal chunk_index
        text = text.strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "level1": level1,
                    "level2": level2,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

    def flush() -> None:
        emit("".join(buffer))
        buffer.clear()

    for style_name, text in rows:
        if not text:
            continue
        heading = _heading_level(style_name, text)
        if heading == 1:
            flush()
            level1, level2 = _strip_number_prefix(text), ""
        elif heading == 2:
            flush()
            level2 = _strip_number_prefix(text)
        else:
            buffer.append(text + "\n")
            total = sum(len(part) for part in buffer)
            if total >= settings.template_chunk_size:
                joined = "".join(buffer).strip()
                cut = max(total - settings.template_chunk_overlap, 1)
                emit(joined[:cut])
                buffer[:] = [joined[cut:] + "\n"] if joined[cut:] else []
    flush()
    return chunks


def _heading_level(style_name: str, text: str) -> int | None:
    """识别段落标题层级：样式优先，其次编号启发式。"""
    if len(text) > _MAX_HEADING_LENGTH:
        return None
    level = _style_level((style_name or "").lower())
    if level:
        return min(level, 2)
    detected = _detect_level(text)
    if detected is not None and _numbered_tail_looks_like_title(text):
        return min(detected, 2)
    return None
