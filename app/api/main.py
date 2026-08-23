"""FastAPI 应用入口：uvicorn app.api.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import setup_logging

setup_logging()

app = FastAPI(
    title="agent-paper-assistant",
    description="基于多 Agent 协作的学术论文辅助生成系统",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
