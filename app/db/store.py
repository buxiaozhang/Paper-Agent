"""持久化存储服务：论文历史、大纲与章节内容的读写。"""

import logging
from datetime import datetime

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base, PaperOutline, PaperRecord, PaperSection

logger = logging.getLogger(__name__)


class PaperStore:
    """论文数据存储：支持 MySQL / SQLite（由 DATABASE_URL 决定）。"""

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        # 兼容旧配置：同步引擎不识别 sqlite+aiosqlite 驱动前缀
        if url.startswith("sqlite+aiosqlite"):
            url = url.replace("sqlite+aiosqlite", "sqlite", 1)
        engine_kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(url, **engine_kwargs)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        """创建数据表（幂等）。"""
        Base.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """轻量迁移：为旧库的 outlines 表补充 subsections 列。"""
        try:
            with self.engine.begin() as conn:
                if self.engine.dialect.name == "sqlite":
                    columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(outlines)")]
                    if columns and "subsections" not in columns:
                        conn.exec_driver_sql("ALTER TABLE outlines ADD COLUMN subsections JSON")
                elif self.engine.dialect.name == "mysql":
                    exists = conn.exec_driver_sql(
                        "SHOW COLUMNS FROM outlines LIKE 'subsections'"
                    ).fetchall()
                    if not exists:
                        conn.exec_driver_sql("ALTER TABLE outlines ADD COLUMN subsections JSON NULL")
        except Exception as exc:  # 迁移失败不影响启动
            logger.warning("数据库迁移检查失败：%s", exc)

    # ---------- 历史记录 ----------
    def create_record(self, user_id: str, topic: str, title: str = "") -> int:
        """新建生成记录，返回 paper_id。"""
        with Session(self.engine) as session:
            record = PaperRecord(user_id=user_id, topic=topic, title=title, status="running")
            session.add(record)
            session.commit()
            return record.id

    def update_record(self, paper_id: int, title: str | None = None, status: str | None = None) -> None:
        """更新生成记录的状态 / 标题。"""
        with Session(self.engine) as session:
            record = session.get(PaperRecord, paper_id)
            if record is None:
                return
            if title is not None:
                record.title = title
            if status is not None:
                record.status = status
            session.commit()

    def list_records(self, user_id: str, limit: int = 50) -> list[dict]:
        """按时间倒序返回用户的历史生成记录。"""
        with Session(self.engine) as session:
            records = session.scalars(
                select(PaperRecord)
                .where(PaperRecord.user_id == user_id)
                .order_by(PaperRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "topic": r.topic,
                    "title": r.title,
                    "status": r.status,
                    "created_at": _iso(r.created_at),
                    "updated_at": _iso(r.updated_at),
                }
                for r in records
            ]

    def get_paper(self, paper_id: int) -> dict | None:
        """读取论文记录、大纲与全部章节。"""
        with Session(self.engine) as session:
            record = session.get(PaperRecord, paper_id)
            if record is None:
                return None
            outlines = session.scalars(
                select(PaperOutline)
                .where(PaperOutline.paper_id == paper_id)
                .order_by(PaperOutline.section_order)
            ).all()
            sections = session.scalars(
                select(PaperSection)
                .where(PaperSection.paper_id == paper_id)
                .order_by(PaperSection.section_order)
            ).all()
            return {
                "id": record.id,
                "user_id": record.user_id,
                "topic": record.topic,
                "title": record.title,
                "status": record.status,
                "created_at": _iso(record.created_at),
                "updated_at": _iso(record.updated_at),
                "outline": [
                    {"title": o.title, "subsections": list(o.subsections or [])}
                    for o in outlines
                ],
                "sections": [
                    {
                        "section_order": s.section_order,
                        "title": s.title,
                        "content": s.content,
                        "summary": s.summary,
                    }
                    for s in sections
                ],
            }

    # ---------- 大纲 ----------
    def save_outline(self, paper_id: int, structure: list[dict]) -> None:
        """覆盖写入大纲表。structure: [{"title": 一级标题, "subsections": [二级...]}]"""
        with Session(self.engine) as session:
            session.execute(delete(PaperOutline).where(PaperOutline.paper_id == paper_id))
            for index, item in enumerate(structure):
                session.add(
                    PaperOutline(
                        paper_id=paper_id,
                        section_order=index,
                        title=item.get("title", ""),
                        subsections=list(item.get("subsections", [])),
                    )
                )
            session.commit()

    # ---------- 章节内容 ----------
    def save_sections(self, paper_id: int, items: list[dict]) -> None:
        """覆盖写入内容表。items: [{"title", "content", "summary"}]"""
        with Session(self.engine) as session:
            session.execute(delete(PaperSection).where(PaperSection.paper_id == paper_id))
            for index, item in enumerate(items):
                session.add(
                    PaperSection(
                        paper_id=paper_id,
                        section_order=index,
                        title=item["title"],
                        content=item["content"],
                        summary=item.get("summary", ""),
                    )
                )
            session.commit()


def _iso(value: datetime | None) -> str:
    """datetime -> ISO 字符串。"""
    return value.isoformat() if value else ""
