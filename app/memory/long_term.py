"""长期记忆管理：基于 ChromaDB 的向量存储。

将论文、文献摘要与生成记录向量化后持久化，支持相似性检索，
为后续论文生成提供可复用的知识上下文。
"""

from functools import lru_cache

from langchain_chroma import Chroma

from app.config import settings


@lru_cache
def get_vector_store() -> Chroma:
    """返回全局唯一的 Chroma 向量库实例（持久化到 CHROMA_DIR）。

    默认使用 Chroma 内置本地 embedding（无需外部 API）；
    如需更换 embedding，可传入自定义 embedding_function。
    """
    return Chroma(
        collection_name=settings.chroma_collection,
        persist_directory=settings.chroma_dir,
    )


class LongTermMemory:
    """长期记忆：文档 / 文献的向量化存取与相似性检索。"""

    def __init__(self) -> None:
        self.store = get_vector_store()

    def add_texts(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        """向量化并存储文本及其元数据。"""
        self.store.add_texts(texts=texts, metadatas=metadatas)

    def search(self, query: str, top_k: int = 4) -> list[tuple[str, dict]]:
        """相似性检索：返回 (文本, 元数据) 列表。"""
        results = self.store.similarity_search(query, k=top_k)
        return [(doc.page_content, doc.metadata) for doc in results]
