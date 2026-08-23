"""FastAPI 路由：论文生成接口。"""

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
from app.tools.outline import extract_outline

router = APIRouter()
assistant = PaperAssistantAgent()
store = PaperStore()
store.init_db()

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
    sections = await _read_template_outline(file)
    if not sections:
        raise HTTPException(status_code=400, detail="未能从模板中提取到大纲")
    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    return OutlineResponse(filename=file.filename or "", source=suffix, sections=sections)


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
    template_outline = await _read_template_outline(file)
    try:
        result = assistant.generate(
            topic,
            max_revisions=max_revisions,
            template_outline=template_outline,
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


async def _read_template_outline(file: UploadFile | None) -> list[str] | None:
    """读取上传文件并提取大纲；无文件返回 None，格式不支持或解析失败抛 400。"""
    if file is None:
        return None
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in TEMPLATE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 .docx 或 .pdf 格式的模板文件")
    try:
        content = await file.read()
        return extract_outline(filename, content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模板解析失败：{exc}") from exc
