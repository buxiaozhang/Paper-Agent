"""文献检索工具：OpenAlex API 与 Semantic Scholar API。"""

from typing import Literal

import httpx,logging
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

class PaperReference(BaseModel):
    """标准化后的文献条目。"""

    title: str = ""
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    url: str | None = None
    citations: int | None = None
    source: Literal["openalex", "semantic_scholar"] = "openalex"


class LiteratureSearchTool:
    """学术文献检索工具，支持 OpenAlex 与 Semantic Scholar。"""

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """按主题检索文献，OpenAlex 失败时回退到 Semantic Scholar，都失败降级为空列表"""
        try:
            results = self.search_openalex(query, limit)
            if results:
                return results
            results = self.search_semantic_scholar(query, limit)
            if results:
                return results
        except httpx.HTTPError:
            pass
        logger.info("未检索到文献，返回空列表")
        return []

    def search_openalex(self, query: str, limit: int = 5) -> list[dict]:
        """调用 OpenAlex works 接口检索文献。"""
        params = {"search": query, "per_page": limit, "mailto": "agent-paper-assistant@example.com"}
        response = self.client.get(f"{settings.openalex_base_url}/works", params=params)
        response.raise_for_status()
        items = []
        for work in response.json().get("results", []):
            items.append(
                PaperReference(
                    title=work.get("title", ""),
                    year=work.get("publication_year"),
                    authors=[a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])],
                    doi=work.get("doi"),
                    url=work.get("id"),
                    citations=work.get("cited_by_count"),
                    source="openalex",
                ).model_dump()
            )
        return items

    def search_semantic_scholar(self, query: str, limit: int = 5) -> list[dict]:
        """调用 Semantic Scholar graph 接口检索文献。"""
        params = {"query": query, "limit": limit}
        headers = {}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        response = self.client.get(
            f"{settings.semantic_scholar_base_url}/graph/v1/paper/search",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        items = []
        for paper in response.json().get("data", []):
            items.append(
                PaperReference(
                    title=paper.get("title", ""),
                    year=paper.get("year"),
                    authors=[a.get("name", "") for a in paper.get("authors", [])],
                    doi=paper.get("externalIds", {}).get("DOI"),
                    url=paper.get("url"),
                    citations=paper.get("citationCount"),
                    source="semantic_scholar",
                ).model_dump()
            )
        return items
