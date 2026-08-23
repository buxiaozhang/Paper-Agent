# agent-paper-assistant

基于多 Agent 协作的学术论文辅助生成系统。使用 LangGraph 编排论文生成流水线（文献检索 → 大纲 → 撰写 → 评审修订 → 配图），提供 FastAPI 服务与 Streamlit 交互界面。

## 技术栈

- **编排框架**：LangGraph + LangChain
- **LLM**：DeepSeek API（默认，OpenAI 兼容接口），可切换 OpenAI GPT-4o
- **服务层**：FastAPI + Streamlit
- **文档处理**：python-docx、docxtpl、pypdf（模板大纲提取）
- **数据库**：Redis（短期记忆 / 缓存）、PostgreSQL / SQLite（业务数据）
- **向量数据库**：ChromaDB（长期记忆）
- **文献检索**：OpenAlex API、Semantic Scholar API
- **图片生成**：阿里云通义万相（DashScope，预留接口）
- **对象存储**：阿里云 OSS（预留）

## 项目结构

```
.
├── pyproject.toml            # Poetry 依赖与构建配置
├── .env.example              # 环境变量模板
├── .gitignore
├── README.md
└── app/
    ├── __init__.py
    ├── config.py             # 配置管理（API keys、Redis、数据库连接）
    ├── agents/               # 各 Agent 节点
    │   ├── base.py           # Agent 基类与 LLM 初始化
    │   ├── research.py       # 研究 Agent、撰写 Agent、评审 Agent
    │   ├── image_gen.py      # 配图 Agent
    │   └── coordinator.py    # 流水线协调入口
    ├── graph/                # LangGraph 状态图定义
    │   ├── state.py          # 共享状态（PaperState）
    │   └── builder.py        # 状态图构建与编译
    ├── tools/                # 外部工具
    │   ├── literature.py     # OpenAlex / Semantic Scholar 文献检索
    │   ├── image_generation.py  # 通义万相图片生成（预留）
    │   ├── document.py       # docx 解析与生成
    │   └── outline.py        # docx / pdf 模板大纲提取与默认大纲
    ├── memory/               # 记忆管理
    │   ├── short_term.py     # Redis 短期记忆（自动降级为内存）
    │   └── long_term.py      # ChromaDB 长期记忆
    ├── api/                  # FastAPI 路由
    │   ├── main.py           # 应用入口
    │   ├── routes.py         # 论文生成等接口
    │   └── schemas.py        # 请求 / 响应模型
    └── ui/                   # Streamlit 前端
        └── streamlit_app.py  # 前端入口（勿改名为 app.py，会遮蔽 app 包）
```

## 快速开始

要求：Python 3.11 与 Poetry。

```bash
# 1. 安装依赖（PostgreSQL 可选依赖一并安装）
poetry env use 3.11          # 确保使用 Python 3.11
poetry install --with postgres,dev

# 2. 配置环境变量
cp .env.example .env
# Windows PowerShell：Copy-Item .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY

# 3. 启动 FastAPI 服务
poetry run uvicorn app.api.main:app --reload

# 4. 启动 Streamlit 前端（另一个终端）
poetry run streamlit run app/ui/streamlit_app.py
```

API 文档：启动后访问 http://127.0.0.1:8000/docs

主要接口：

- `GET  /api/v1/health`：健康检查
- `POST /api/v1/papers/generate`：触发论文生成，请求体 `{"topic": "...", "max_revisions": 2}`
- `POST /api/v1/papers/generate-with-template`：带模板生成，multipart 表单字段 `topic`、`max_revisions`、`file`（docx/pdf，可选；模板大纲优先于默认大纲）
- `POST /api/v1/templates/extract-outline`：上传模板提取大纲，multipart 表单字段 `file`

## 环境变量

复制 `.env.example` 为 `.env` 后按需填写，所有变量均可通过环境变量覆盖：

| 变量 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填，默认 LLM） |
| `OPENAI_API_KEY` | 可选，切换到 GPT-4o 时使用 |
| `REDIS_URL` | Redis 连接串，如 `redis://localhost:6379/0` |
| `DATABASE_URL` | 数据库连接串；开发环境默认 `sqlite+aiosqlite:///./paper_agent.db` |
| `CHROMA_DIR` | ChromaDB 持久化目录 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | 阿里云 OSS 凭证（预留） |
| `ALIYUN_DASHSCOPE_API_KEY` | 通义万相（DashScope）API Key（预留） |
| `LLM_PROVIDER` | LLM 提供方：`deepseek`（默认）或 `openai` |
| `DEFAULT_MODEL` | 默认模型名，如 `deepseek-chat` / `gpt-4o` |
| `OPENALEX_BASE_URL` | OpenAlex API 地址，默认官方地址 |
| `SEMANTIC_SCHOLAR_BASE_URL` | Semantic Scholar API 地址，默认官方地址 |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar API Key（可选，提高请求限额） |
| `OSS_ENDPOINT` / `OSS_BUCKET` | 阿里云 OSS 地域与桶名（预留） |
| `ALIYUN_WANX_MODEL` | 通义万相模型名，默认 `wanx-v1` |

## 切换 LLM

默认使用 DeepSeek。切换到 OpenAI GPT-4o：

```bash
# .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
DEFAULT_MODEL=gpt-4o
```

## 数据库说明

- 开发环境默认使用 SQLite（`sqlite+aiosqlite:///./paper_agent.db`），无需额外服务。
- 生产环境可将 `DATABASE_URL` 改为 `postgresql+asyncpg://user:password@localhost:5432/paper_agent`，并确保已安装 postgres 依赖组（`poetry install --with postgres`）。

## 常见问题

- **Streamlit 报 `No module named 'app.agents'; 'app' is not a package`**：入口文件必须命名为 `streamlit_app.py`。Streamlit 会把脚本所在目录 `app/ui` 加入 `sys.path`，若入口名为 `app.py`，`import app` 会命中脚本文件本身（普通模块）而非项目包。入口文件内置的路径引导会把项目根目录（含 `pyproject.toml` 的目录）插入 `sys.path` 首位，正常启动命令：
  ```bash
  poetry run streamlit run app/ui/streamlit_app.py
  ```
- **未配置 Redis**：`ShortTermMemory` 自动降级为进程内内存，开发环境可直接使用；生产环境请配置 `REDIS_URL`。
- **未配置 `ALIYUN_DASHSCOPE_API_KEY`**：配图节点返回占位结果，不影响流水线其余环节。

## 设计说明

- **状态**：`app/graph/state.py` 中的 `PaperState` 为 TypedDict，保持可序列化；Agent 与工具实例通过闭包注入状态图，不放入共享状态。
- **大纲来源**：上传 docx / pdf 模板时，从标题样式 / PDF 书签（或文本启发式）提取大纲；未上传或提取为空时回退默认大纲（引言、相关工作、方法、实验与结果、结论）。
- **日志**：流水线每个节点输出 `STEP n/total（百分比）| 步骤名` 日志（如文献检索、大纲生成、论文撰写、评审修订、配图生成），在 uvicorn / Streamlit 启动的控制台可见。
- **进度**：`PaperAssistantAgent.generate()` 支持 `progress_callback(percent, step_name)` 进度回调；Streamlit 前端以进度条实时展示百分比与当前步骤。
- **记忆**：`ShortTermMemory` 在 Redis 不可用时自动降级为进程内内存，便于本地开发；`LongTermMemory` 使用 ChromaDB 持久化向量。
- **扩展点**：`WanxImageTool` 与 OSS 上传为预留接口，配置 `ALIYUN_DASHSCOPE_API_KEY` 后接入 DashScope 异步任务接口即可启用。
- **入口引导**：`app/ui/streamlit_app.py` 启动时向上定位项目根目录并插入 `sys.path` 首位，保证 `app` 包在任何启动目录下都能被正确导入。

