"""LangGraph 状态定义：论文生成流水线的共享状态。"""

from typing import TypedDict


class PaperState(TypedDict, total=False):
    """流水线节点间共享的状态。

    字段均为可选（total=False），便于按需写入；
    如需跨节点追加合并可用 Annotated[list, operator.add] 声明 reducer。
    """

    topic: str                  # 论文主题
    title: str                  # 论文标题
    sections: list[str]         # 章节大纲
    template_outline: list[str] | None  # 从上传模板提取的大纲（优先于默认大纲）
    draft: str                  # 当前草稿全文
    references: list[dict]      # 检索到的文献列表
    images: list[dict]          # 生成 / 预留的配图信息
    feedback: str               # 最近一次评审意见
    revision_count: int         # 已修订次数
    max_revisions: int          # 最大修订次数
    status: str                 # draft / reviewing / done
    step: str                   # 当前节点名称（用于日志与前端进度展示）
