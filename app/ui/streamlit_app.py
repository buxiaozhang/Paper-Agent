"""Streamlit 前端：交互式论文生成界面。

运行：streamlit run app/ui/streamlit_app.py
"""

import sys
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

import streamlit as st

from app.agents.coordinator import PaperAssistantAgent
from app.tools.document import build_paper_docx

st.set_page_config(page_title="agent-paper-assistant", page_icon="📄", layout="wide")
st.title("📄 学术论文辅助生成系统（多 Agent 协作）")

topic = st.text_input("论文主题 / 研究问题", placeholder="例如：基于多智能体协作的文献综述自动生成方法")
max_revisions = st.slider("评审-修订最大轮数", min_value=1, max_value=5, value=2)

if st.button("开始生成", type="primary", disabled=not topic):
    with st.spinner("多 Agent 流水线运行中（检索 -> 大纲 -> 撰写 -> 评审 -> 配图）..."):
        assistant = PaperAssistantAgent()
        result = assistant.generate(topic, max_revisions=max_revisions)

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
