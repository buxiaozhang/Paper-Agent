"""Streamlit 前端：交互式论文生成界面。

运行：streamlit run app/ui/streamlit_app.py
"""

import sys
import threading
import time
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

from app.agents.coordinator import PaperAssistantAgent
from app.tools.document import build_paper_docx
from app.tools.outline import extract_outline

st.set_page_config(page_title="agent-paper-assistant", page_icon="📄", layout="wide")
st.title("📄 学术论文辅助生成系统（多 Agent 协作）")

topic = st.text_input("论文主题 / 研究问题", placeholder="例如：基于多智能体协作的文献综述自动生成方法")
max_revisions = st.slider("评审-修订最大轮数", min_value=1, max_value=5, value=2)

uploaded_template = st.file_uploader(
    "上传大纲模板（.docx / .pdf，可选；未上传时使用默认大纲）",
    type=["docx", "pdf"],
)

template_outline: list[str] | None = None
if uploaded_template is not None:
    try:
        template_outline = extract_outline(uploaded_template.name, uploaded_template.getvalue())
        st.success(f"已从模板提取 {len(template_outline)} 个章节：")
        st.caption("、".join(template_outline))
    except Exception:
        template_outline = None
        st.error("模板解析失败，本次生成将使用默认大纲")

if st.button("开始生成", type="primary", disabled=not topic):
    progress_bar = st.progress(0, text="准备开始…")
    shared: dict = {"percent": 0, "step": "准备开始", "result": None, "error": None, "done": False}

    def _on_progress(percent: int, step_name: str) -> None:
        """后台线程回调：仅写入共享字典，由主线程刷新进度条。"""
        shared["percent"] = percent
        shared["step"] = step_name

    def _run() -> None:
        """后台线程：执行多 Agent 流水线并捕获异常。"""
        try:
            assistant = PaperAssistantAgent()
            shared["result"] = assistant.generate(
                topic=topic,
                max_revisions=max_revisions,
                template_outline=template_outline,
                progress_callback=_on_progress,
            )
        except Exception as exc:
            shared["error"] = exc
        finally:
            shared["done"] = True

    threading.Thread(target=_run, daemon=True).start()

    while not shared["done"]:
        progress_bar.progress(
            shared["percent"] / 100,
            text=f"{shared['step']}（{shared['percent']}%）",
        )
        time.sleep(0.2)
    progress_bar.progress(1.0, text="生成完成（100%）")

    if shared["error"] is not None:
        st.error(f"生成失败：{shared['error']}")
    else:
        result = shared["result"]
        st.subheader(result["title"])
        for section in result["sections"]:
            st.markdown(f"**{section}**")
        with st.expander("查看草稿全文", expanded=True):
            st.markdown(result["draft"])

        if result["references"]:
            st.subheader("参考文献")
            for ref in result["references"]:
                st.markdown(f"- {ref.get('title', '')}（{ref.get('year', '')}）")

        if result["images"]:
            st.subheader("配图")
            for image in result["images"]:
                st.json(image)

        # 导出 .docx（导出内容依赖 draft 格式，此处提供基础导出示例）
        try:
            sections = {"正文": result["draft"]}
            build_paper_docx(result["title"], sections, "paper_draft.docx")
            with open("paper_draft.docx", "rb") as f:
                st.download_button("下载 Word 草稿", f, file_name="paper.docx")
        except OSError:
            st.warning("Word 导出暂不可用")
