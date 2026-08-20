"""FastAPI 路由：论文生成接口。"""

from fastapi import APIRouter

from app import __version__
from app.agents.coordinator import PaperAssistantAgent
from app.api.schemas import HealthResponse, PaperGenerateRequest, PaperGenerateResponse
from app.memory.short_term import ShortTermMemory

router = APIRouter()
assistant = PaperAssistantAgent()
short_memory = ShortTermMemory()


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
