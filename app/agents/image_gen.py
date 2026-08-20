"""图片生成 Agent：调用通义万相等模型为论文生成配图（预留实现）。"""

from app.agents.base import BaseAgent
from app.tools.image_generation import WanxImageTool


class ImageAgent(BaseAgent):
    """论文配图生成 Agent。"""

    name = "illustrator"
    description = "论文配图生成 Agent"

    def __init__(self, wanx_tool: WanxImageTool | None = None) -> None:
        super().__init__()
        self.wanx_tool = wanx_tool or WanxImageTool()

    def run(self, topic: str) -> list[dict]:
        """为论文主题生成配图描述，并调用通义万相（未配置 Key 时仅返回占位结果）。"""
        prompt = f"请为论文「{topic}」设计 1 张学术示意图，输出中文提示词。"
        caption = str(self.llm.invoke(prompt).content)
        return self.wanx_tool.generate(caption)
