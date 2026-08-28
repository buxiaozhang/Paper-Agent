"""Streamlit 前端：交互式论文生成界面。

运行：streamlit run app/ui/streamlit_app.py
"""

import hashlib
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    """将项目根目录插入 sys.path 首位，保证 `app` 包可被正确导入。

    Streamlit 会把脚本所在目录（app/ui）加入 sys.path；若入口文件名与包名
    同名（app.py），`import app` 会命中脚本文件本身而非包，导致
    "No module named 'app.agents'; 'app' is not a package"。
    这里无条件向上定位包含 pyproject.toml 的项目根目录并插入 sys.path[0]。
    """
    raw_file = globals().get("__file__")
    starts = [Path(raw_file).resolve().parent] if raw_file else []
    starts.append(Path.cwd())
    seen: set[Path] = set()
    for start in starts:
        for parent in (start, *start.parents):
            if parent in seen:
                continue
            seen.add(parent)
            if (parent / "pyproject.toml").is_file():
                sys.path.insert(0, str(parent))
                return


_ensure_project_root_on_path()

# Streamlit 长驻进程中只重跑入口脚本，不会重载已导入的 app 模块；
# 每次重跑前清除 app 相关缓存，保证代码修改（如新增函数参数）立即生效。
for _cached in [name for name in sys.modules if name == "app" or name.startswith("app.")]:
    del sys.modules[_cached]

import streamlit as st

from app.agents.coordinator import PaperAssistantAgent, PaperBusyError
from app.db.store import PaperStore
from app.memory.short_term import ShortTermMemory, lock_key, progress_key
from app.tools.document import build_paper_docx
from app.tools.outline import extract_outline, extract_outline_structure
from app.tools.template_index import TemplateIndex

# UI、生成线程与数据库共用同一批实例，保证无 Redis 时进程内数据仍互通
memory = ShortTermMemory()
store = PaperStore()
store.init_db()
template_index = TemplateIndex()

PROGRESS_STALE_SECONDS = 7200


def _fmt_time(iso: str) -> str:
    """ISO 时间 -> 本地可读时间。"""
    if not iso:
        return ""
    try:
        value = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _is_stale(payload: dict) -> bool:
    """判断 running 状态的任务是否已失效（如服务重启导致线程丢失）。"""
    if payload.get("status") != "running":
        return False
    try:
        updated = datetime.fromisoformat(payload["updated_at"])
    except (KeyError, ValueError):
        return True
    return datetime.utcnow() - updated > timedelta(seconds=PROGRESS_STALE_SECONDS)


def _render_paper(paper: dict) -> None:
    """渲染数据库中的论文（大纲 + 章节内容 + 摘要）。"""
    st.subheader(paper.get("title") or paper.get("topic"))
    st.caption(
        f"状态：{paper.get('status')} ｜ 生成时间：{_fmt_time(paper.get('created_at'))}"
    )
    if paper.get("outline"):
        st.markdown("**大纲**：")
        for item in paper["outline"]:
            st.markdown(f"- {item.get('title', '')}")
            for sub in item.get("subsections", []):
                if isinstance(sub, dict):
                    st.markdown(f"    - {sub.get('title', '')}")
                    for subsub in sub.get("subsections", []):
                        st.markdown(f"        - {subsub}")
                else:
                    st.markdown(f"    - {sub}")
    for section in paper.get("sections", []):
        with st.expander(f"{section['title']}（摘要：{(section.get('summary') or '')[:80]}）"):
            st.markdown(section["content"])


def _wait_for_progress(user_id: str, topic: str) -> dict | None:
    """轮询 Redis 进度直至任务结束，返回最终进度负载。"""
    progress_bar = st.progress(0, text="等待任务进度…")
    last_percent = -1
    while True:
        payload = memory.get_progress(user_id, topic)
        if payload:
            if _is_stale(payload):
                memory.delete(progress_key(user_id, topic))
                memory.release_lock(lock_key(user_id))
                st.warning("检测到失效任务（可能因服务重启中断），已清理，可重新生成")
                return None
            percent = int(payload.get("percent", 0))
            step = payload.get("step", "")
            if percent != last_percent:
                progress_bar.progress(percent / 100, text=f"{step}（{percent}%）")
                last_percent = percent
            if payload.get("status") in ("done", "error"):
                progress_bar.progress(1.0 if payload["status"] == "done" else 0.0,
                                      text=f"{step}（{payload['status']}）")
                return payload
        time.sleep(0.5)


def _load_and_render(paper_id: int) -> None:
    """从数据库读取并渲染已生成论文。"""
    if not paper_id:
        st.warning("未在数据库中找到该论文记录")
        return
    paper = store.get_paper(paper_id)
    if paper:
        _render_paper(paper)
    else:
        st.warning("未在数据库中找到该论文记录")


def _start_new_generation() -> None:
    """清空上一次展示的内容，回到新生成页面。"""
    st.session_state["view"] = "generate"
    st.session_state["view_paper_id"] = None
    st.session_state["result_paper_id"] = None


st.set_page_config(page_title="agent-paper-assistant", page_icon="📄", layout="wide")
st.title("📄 学术论文辅助生成系统（多 Agent 协作）")

# ---------- 视图状态：默认（首次打开）为新生成页面 ----------
if "view" not in st.session_state:
    st.session_state["view"] = "generate"
if "view_paper_id" not in st.session_state:
    st.session_state["view_paper_id"] = None
if "result_paper_id" not in st.session_state:
    st.session_state["result_paper_id"] = None

# ---------- 侧栏：历史生成记录（主题与时间） ----------
with st.sidebar:
    st.header("历史生成记录")
    history_user = st.text_input("历史记录用户 ID", value="default_user", key="history_user")
    records = store.list_records(history_user, limit=30)
    if not records:
        st.caption("暂无历史记录")
    for record in records:
        label = f"{_fmt_time(record['created_at'])} ｜ {record['topic'][:24]}"
        if st.button(label, key=f"history_{record['id']}", use_container_width=True):
            st.session_state["view"] = "paper"
            st.session_state["view_paper_id"] = record["id"]
            st.session_state["result_paper_id"] = None

# ---------- 论文详情视图（历史 / 上次结果） ----------
if st.session_state["view"] == "paper":
    if st.button("开始新生成", type="primary"):
        _start_new_generation()
        st.rerun()
    st.markdown("### 历史论文详情")
    _load_and_render(st.session_state["view_paper_id"])
else:
    # ============ 新生成页面 ============
    user_id = st.text_input("用户 ID", value="default_user", help="同一用户同时只能生成一篇论文")
    topic = st.text_input("论文主题 / 研究问题", placeholder="例如：基于多智能体协作的文献综述自动生成方法")
    max_revisions = st.slider("评审-修订最大轮数", min_value=1, max_value=5, value=2)

    uploaded_template = st.file_uploader(
        "上传大纲模板（.docx / .pdf，可选；未上传时使用默认大纲）",
        type=["docx", "pdf"],
    )

    template_outline: list[str] | None = None
    template_hierarchy: list[dict] | None = None
    template_id: str | None = None
    if uploaded_template is not None:
        content = uploaded_template.getvalue()
        cache_key = f"{uploaded_template.name}:{hashlib.sha256(content).hexdigest()[:12]}"
        # 会话内缓存解析与向量化结果，避免每次 rerun 重复解析 / 重复向量化模板
        if st.session_state.get("template_cache_key") == cache_key:
            template_outline = st.session_state.get("template_outline_cache")
            template_hierarchy = st.session_state.get("template_hierarchy_cache")
            template_id = st.session_state.get("template_id_cache")
        else:
            try:
                template_outline = extract_outline(uploaded_template.name, content)
                template_hierarchy = extract_outline_structure(uploaded_template.name, content)
                st.success(f"已从模板提取 {len(template_outline)} 个一级章节：")
                try:
                    index_result = template_index.index_template(
                        uploaded_template.name, content, user_id=user_id
                    )
                    template_id = index_result.template_id
                    st.info(
                        f"模板已切片写入向量库（{index_result.chunk_count} 个片段），"
                        "写作时将参考模板写法"
                    )
                except Exception as exc:
                    st.warning(f"模板向量化失败（不影响生成，但不提供模板写法参考）：{exc}")
            except Exception:
                template_outline = None
                template_hierarchy = None
                st.error("模板解析失败，本次生成将使用默认大纲")
            st.session_state["template_cache_key"] = cache_key
            st.session_state["template_outline_cache"] = template_outline
            st.session_state["template_hierarchy_cache"] = template_hierarchy
            st.session_state["template_id_cache"] = template_id
        if template_hierarchy:
            preview = []
            for item in template_hierarchy:
                level = item.get("level", 1)
                if level == 3:
                    prefix = "        - "
                elif level == 2:
                    prefix = "    - "
                else:
                    prefix = "- "
                preview.append(f"{prefix}{item.get('title', '')}")
            st.caption("\n".join(preview))

    # ---------- 刷新恢复：仅跟踪进行中的任务；历史完成内容不自动展示 ----------
    active = memory.find_active_progress(user_id)
    if active and not _is_stale(active) and active.get("status") == "running":
        st.info(f"检测到进行中的任务「{active.get('topic')}」，正在恢复进度…")
        final = _wait_for_progress(user_id, active["topic"])
        if final and final.get("status") == "done" and final.get("paper_id"):
            st.session_state["result_paper_id"] = final["paper_id"]
        elif final and final.get("status") == "error":
            st.error(f"上次任务生成失败：{final.get('step')}")
    elif active and _is_stale(active):
        memory.delete(progress_key(user_id, active.get("topic", "")))
        memory.release_lock(lock_key(user_id))

    # ---------- 生成 ----------
    if st.button("开始生成", type="primary", disabled=not topic):
        st.session_state["result_paper_id"] = None  # 开始新任务时不再展示上一次内容
        thread_error: dict = {"error": None}
        thread_done: dict = {"done": False}

        def _run() -> None:
            """后台线程：执行流水线；进度由协调器写入 Redis，主线程轮询读取。"""
            try:
                assistant = PaperAssistantAgent(short_memory=memory, store=store)
                assistant.generate(
                    topic=topic,
                    max_revisions=max_revisions,
                    template_outline=template_outline,
                    template_hierarchy=template_hierarchy,
                    template_id=template_id,
                    user_id=user_id,
                )
            except Exception as exc:
                thread_error["error"] = exc
            finally:
                thread_done["done"] = True

        threading.Thread(target=_run, daemon=True).start()

        progress_bar = st.progress(0, text="准备开始…")
        last_percent = -1
        final = None
        while True:
            payload = memory.get_progress(user_id, topic)
            if payload and not _is_stale(payload):
                percent = int(payload.get("percent", 0))
                step = payload.get("step", "")
                if percent != last_percent:
                    progress_bar.progress(percent / 100, text=f"{step}（{percent}%）")
                    last_percent = percent
                if payload.get("status") in ("done", "error"):
                    final = payload
                    break
            elif thread_done["done"]:
                break  # 线程已结束但未写入进度（如并发冲突被拒绝）
            time.sleep(0.5)

        if isinstance(thread_error["error"], PaperBusyError):
            st.warning(str(thread_error["error"]))
            # 已有任务进行中：改为跟随现有任务进度
            running = memory.find_active_progress(user_id)
            if running and running.get("status") == "running" and not _is_stale(running):
                final = _wait_for_progress(user_id, running["topic"])
        elif thread_error["error"] is not None:
            st.error(f"生成失败：{thread_error['error']}")

        if final and final.get("status") == "done" and final.get("paper_id"):
            st.session_state["result_paper_id"] = final["paper_id"]
        elif final and final.get("status") == "error":
            st.error(f"生成失败：{final.get('step')}")

    # ---------- 当前会话生成结果展示（可一键返回新生成页面） ----------
    if st.session_state.get("result_paper_id"):
        st.divider()
        col_new, col_tip = st.columns([1, 4])
        if col_new.button("开始新生成", type="primary"):
            _start_new_generation()
            st.rerun()
        with col_tip:
            st.success("生成完成，已持久化到数据库")
        _load_and_render(st.session_state["result_paper_id"])

        # 导出 .docx（基于数据库中最新章节）
        try:
            paper = store.get_paper(st.session_state["result_paper_id"])
            if paper and paper.get("sections"):
                sections = {s["title"]: s["content"] for s in paper["sections"]}
                build_paper_docx(paper.get("title") or topic, sections, "paper_draft.docx")
                with open("paper_draft.docx", "rb") as f:
                    st.download_button("下载 Word 草稿", f, file_name="paper.docx")
        except OSError:
            st.warning("Word 导出暂不可用")
