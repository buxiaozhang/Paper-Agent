"""FastAPI 请求 / 响应模型。"""

from pydantic import BaseModel, Field


class PaperGenerateRequest(BaseModel):
    """论文生成请求。"""

    topic: str = Field(..., min_length=1, max_length=500, description="论文主题 / 研究问题")
    max_revisions: int = Field(2, ge=1, le=5, description="评审-修订最大轮数")
    user_id: str = Field("default", min_length=1, max_length=128, description="用户 ID")
    template_id: str | None = Field(None, description="模板切片在向量库中的 ID（写作时检索写法参考）")


class PaperGenerateResponse(BaseModel):
    """论文生成结果。"""

    paper_id: int
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
    structure: list[dict]  # 层级大纲：[{"level": 1|2, "title": ...}]
    template_id: str | None = None  # 模板切片向量化后的 ID


class ProgressResponse(BaseModel):
    """生成进度（Redis 中的状态，支持页面刷新恢复）。"""

    paper_id: int | None
    user_id: str
    topic: str
    percent: int
    step: str
    status: str            # running / done / error
    updated_at: str


class HistoryItem(BaseModel):
    """历史生成记录：主题与时间。"""

    id: int
    topic: str
    title: str
    status: str
    created_at: str
    updated_at: str


class SectionItem(BaseModel):
    """内容表中的章节。"""

    section_order: int
    title: str
    content: str
    summary: str


class OutlineItem(BaseModel):
    """大纲表条目：一级标题及其二级标题。"""

    title: str
    subsections: list[str]


class PaperDetailResponse(BaseModel):
    """论文详情：记录 + 大纲 + 章节内容。"""

    id: int
    user_id: str
    topic: str
    title: str
    status: str
    created_at: str
    updated_at: str
    outline: list[OutlineItem]
    sections: list[SectionItem]
