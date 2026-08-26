"""FastAPI 路由：论文生成接口。"""

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import __version__
from app.agents.coordinator import PaperAssistantAgent, PaperBusyError
from app.api.schemas import (
    HealthResponse,
    HistoryItem,
    OutlineResponse,
    PaperDetailResponse,
    PaperGenerateRequest,
    PaperGenerateResponse,
    ProgressResponse,
)
from app.db.store import PaperStore
from app.tools.outline import extract_outline, extract_outline_structure
from app.tools.template_index import TemplateIndex

router = APIRouter()
assistant = PaperAssistantAgent()
store = PaperStore()
store.init_db()
template_index = TemplateIndex()
logger = logging.getLogger(__name__)

TEMPLATE_EXTENSIONS = {".docx", ".pdf"}


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """服务健康检查。"""
    return HealthResponse(status="ok", version=__version__)


@router.post("/papers/generate", response_model=PaperGenerateResponse, tags=["paper"])
def generate_paper(request: PaperGenerateRequest) -> PaperGenerateResponse:
    """触发多 Agent 论文生成流水线。"""
    try:
        result = assistant.generate(
            request.topic,
            max_revisions=request.max_revisions,
            template_id=request.template_id,
            user_id=request.user_id,
        )
    except PaperBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PaperGenerateResponse(**result)


@router.post(
    "/templates/extract-outline",
    response_model=OutlineResponse,
    tags=["template"],
)
async def extract_template_outline(
    file: UploadFile = File(..., description="docx / pdf 大纲模板"),
) -> OutlineResponse:
    """上传 docx / pdf 模板并提取章节大纲。"""
    filename, content = await _read_template_content(file)
    sections, structure = _parse_template(filename, content)
    if not sections:
        raise HTTPException(status_code=400, detail="未能从模板中提取到大纲")
    template_id = _index_template(filename, content, user_id="default")
    suffix = Path(filename).suffix.lower().lstrip(".")
    return OutlineResponse(
        filename=filename,
        source=suffix,
        sections=sections,
        structure=structure or [],
        template_id=template_id,
    )


@router.post(
    "/papers/generate-with-template",
    response_model=PaperGenerateResponse,
    tags=["paper"],
)
async def generate_paper_with_template(
    topic: str = Form(..., min_length=1, max_length=500),
    max_revisions: int = Form(2, ge=1, le=5),
    user_id: str = Form("default", min_length=1, max_length=128),
    file: UploadFile | None = File(None, description="docx / pdf 大纲模板，可选"),
) -> PaperGenerateResponse:
    """上传模板生成论文：模板大纲优先，未上传时使用默认大纲。"""
    template_outline: list[str] | None = None
    template_hierarchy: list[dict] | None = None
    template_id: str | None = None
    if file is not None:
        filename, content = await _read_template_content(file)
        template_outline, template_hierarchy = _parse_template(filename, content)
        logger.info("解析出的template_outline:::::%s", template_outline)
        logger.info("解析出的template_hierarchy:::::%s", template_hierarchy)
        template_id = _index_template(filename, content, user_id=user_id)
    try:
        result = assistant.generate(
            topic,
            max_revisions=max_revisions,
            template_outline=template_outline,
            template_hierarchy=template_hierarchy,
            template_id=template_id,
            user_id=user_id,
        )
    except PaperBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PaperGenerateResponse(**result)


@router.get("/papers/active-progress", response_model=ProgressResponse, tags=["paper"])
def get_active_progress(user_id: str = "default") -> ProgressResponse:
    """返回该用户最近一次任务进度（用于页面刷新恢复）。"""
    payload = assistant.short_memory.find_active_progress(user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="该用户暂无生成任务")
    return ProgressResponse(**payload)


@router.get("/papers/progress", response_model=ProgressResponse, tags=["paper"])
def get_paper_progress(user_id: str = "default", topic: str = "") -> ProgressResponse:
    """按用户 + 主题读取生成进度。"""
    payload = assistant.short_memory.get_progress(user_id, topic)
    if not payload:
        raise HTTPException(status_code=404, detail="未找到该任务的进度")
    return ProgressResponse(**payload)


@router.get("/papers/history", response_model=list[HistoryItem], tags=["paper"])
def list_history(user_id: str = "default", limit: int = 50) -> list[HistoryItem]:
    """历史生成记录：主题与时间（倒序）。"""
    return [HistoryItem(**item) for item in store.list_records(user_id, limit=limit)]


@router.get("/papers/{paper_id}", response_model=PaperDetailResponse, tags=["paper"])
def get_paper_detail(paper_id: int) -> PaperDetailResponse:
    """从数据库读取已生成论文的完整内容。"""
    paper = store.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文记录不存在")
    return PaperDetailResponse(**paper)


async def _read_template_content(file: UploadFile) -> tuple[str, bytes]:
    """校验并一次性读取上传模板，返回 (文件名, 文件内容)。"""
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in TEMPLATE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 .docx 或 .pdf 格式的模板文件")
    try:
        return filename, await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模板读取失败：{exc}") from exc


def _parse_template(filename: str, content: bytes) -> tuple[list[str], list[dict]]:
    """解析模板：返回（一级大纲, 层级大纲）。"""
    try:
        outline = extract_outline(filename, content)
        hierarchy = extract_outline_structure(filename, content)
        return outline, hierarchy
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模板解析失败：{exc}") from exc


def _index_template(filename: str, content: bytes, user_id: str) -> str | None:
    """模板切片向量化；失败时仅告警并返回 None（不影响大纲提取与生成）。"""
    try:
        return template_index.index_template(filename, content, user_id=user_id).template_id
    except Exception:
        logger.warning("模板向量化失败，本次生成不提供模板写法参考", exc_info=True)
        return None
