"""短期记忆管理：基于 Redis 的对话 / 中间状态缓存。

开发环境可使用 fakeredis 或内存实现；本实现提供 Redis 优先、内存降级的
统一接口。
"""

import json
from collections import defaultdict
from typing import Any

import redis

from app.config import settings


class ShortTermMemory:
    """短期记忆：保存流水线中间结果与近期对话上下文（带 TTL）。"""

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        try:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except redis.RedisError:
            self._redis = None  # Redis 不可用时降级为进程内内存
        self._fallback: defaultdict[str, dict[str, Any]] = defaultdict(dict)

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """写入键值，可选过期时间（秒）。"""
        if self._redis is not None:
            self._redis.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
        else:
            self._fallback[key] = {"value": value, "ttl": ttl}

    def get(self, key: str) -> Any:
        """读取键值，不存在时返回 None。"""
        if self._redis is not None:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        entry = self._fallback.get(key)
        return entry["value"] if entry else None
