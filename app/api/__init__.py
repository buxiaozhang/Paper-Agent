"""FastAPI 路由层。"""

from app.api.main import app
from app.api.routes import router
from app.api.schemas import OutlineResponse, PaperGenerateRequest, PaperGenerateResponse

__all__ = ["app", "router", "PaperGenerateRequest", "PaperGenerateResponse", "OutlineResponse"]
