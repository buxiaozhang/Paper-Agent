"""图片生成工具：阿里云通义万相（DashScope）预留接口。

未配置 ALIYUN_DASHSCOPE_API_KEY 时返回占位结果，便于流水线联调。
配置 Key 后可接入 DashScope 的 wanx 系列模型（文本生成图像）。
"""

from typing import Literal

import httpx

from app.config import settings

ImageStatus = Literal["placeholder", "generated", "failed"]


class WanxImageTool:
    """通义万相图片生成工具（预留实现）。"""

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=60.0)
        self.api_key = settings.aliyun_dashscope_api_key
        self.model = settings.aliyun_wanx_model

    def generate(self, prompt: str, size: str = "1024*1024") -> list[dict]:
        """根据文本提示词生成图片，返回图片 URL 或 OSS 上传地址。"""
        if not self.api_key:
            return [
                {
                    "prompt": prompt,
                    "url": None,
                    "status": "placeholder",
                    "note": "未配置 ALIYUN_DASHSCOPE_API_KEY，图片生成接口预留未启用",
                }
            ]
        # TODO: 接入 DashScope 异步任务接口：
        # POST https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis
        # header: Authorization: Bearer <ALIYUN_DASHSCOPE_API_KEY>, X-DashScope-Async: enable
        return [{"prompt": prompt, "url": None, "status": "generated", "size": size}]

    def upload_to_oss(self, image_bytes: bytes, object_name: str) -> str:
        """将图片上传至阿里云 OSS（预留实现，需安装 oss2）。"""
        raise NotImplementedError("OSS 上传接口预留：请在实现后接入 oss2 SDK")
