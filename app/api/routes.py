"""FastAPI 路由：论文生成接口。"""

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import __version__
from app.agents.coordinator import PaperAssistantAgent
from app.api.schemas import (
    HealthResponse,
    OutlineResponse,
    PaperGenerateRequest,
    PaperGenerateResponse,
)
from app.memory.short_term import ShortTermMemory
from app.tools.outline import extract_outline

router = APIRouter()
assistant = PaperAssistantAgent()
short_memory = ShortTermMemory()

TEMPLATE_EXTENSIONS = {".docx", ".pdf"}


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """服务健康检查。"""
    return HealthResponse(status="ok", version=__version__)


@router.post("/papers/generate", response_model=PaperGenerateResponse, tags=["paper"])
def generate_paper(request: PaperGenerateRequest) -> PaperGenerateResponse:
    """触发多 Agent 论文生成流水线。"""
    result = assistant.generate(request.topic, max_revisions=request.max_revisions)
    short_memory.set(f"paper:{result['topic']}", result)
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
    file: UploadFile | None = File(None, description="docx / pdf 大纲模板，可选"),
) -> PaperGenerateResponse:
    """上传模板生成论文：模板大纲优先，未上传时使用默认大纲。"""
    template_outline = await _read_template_outline(file)
    result = assistant.generate(
        topic,
        max_revisions=max_revisions,
        template_outline=template_outline,
    )
    short_memory.set(f"paper:{result['topic']}", result)
    return PaperGenerateResponse(**result)


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
