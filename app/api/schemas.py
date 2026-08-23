"""FastAPI 请求 / 响应模型。"""

from pydantic import BaseModel, Field


class PaperGenerateRequest(BaseModel):
    """论文生成请求。"""

    topic: str = Field(..., min_length=1, max_length=500, description="论文主题 / 研究问题")
    max_revisions: int = Field(2, ge=1, le=5, description="评审-修订最大轮数")


class PaperGenerateResponse(BaseModel):
    """论文生成结果。"""

    topic: str
    title: str
    sections: list[str]
    draft: str
    references: list[dict]
    images: list[dict]
    status: str


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    version: str


class OutlineResponse(BaseModel):
    """模板大纲提取结果。"""

    filename: str
    source: str            # 模板文件类型：docx / pdf
    sections: list[str]
