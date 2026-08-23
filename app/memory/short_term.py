"""短期记忆管理：基于 Redis 的对话 / 中间状态缓存。

开发环境可使用 fakeredis 或内存实现；本实现提供 Redis 优先、内存降级的
统一接口，并支持用户级并发锁与生成进度状态。
"""

import fnmatch
import json
import time
from collections import defaultdict
from typing import Any

import redis

from app.config import settings


def summary_key(user_id: str, topic: str) -> str:
    """章节关键信息摘要的 Redis 键（user_id + 论文主题）。"""
    return f"paper_summary:{user_id}:{topic}"


def progress_key(user_id: str, topic: str) -> str:
    """生成进度的 Redis 键（user_id + 论文主题）。"""
    return f"paper_progress:{user_id}:{topic}"


def lock_key(user_id: str) -> str:
    """用户级生成锁：同一用户同时只能生成一篇论文。"""
    return f"paper_lock:{user_id}"


class ShortTermMemory:
    """短期记忆：保存流水线中间结果与近期对话上下文（带 TTL）。"""

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        try:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except redis.RedisError:
            self._redis = None  # Redis 不可用时降级为进程内内存
        self._fallback: dict[str, dict[str, Any]] = {}

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """写入键值，可选过期时间（秒）。"""
        if self._redis is not None:
            self._redis.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
        else:
            self._fallback[key] = {"value": value, "expires_at": time.time() + ttl}

    def get(self, key: str) -> Any:
        """读取键值，不存在时返回 None。"""
        if self._redis is not None:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        entry = self._fallback.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            self._fallback.pop(key, None)
            return None
        return entry["value"]

    def delete(self, key: str) -> None:
        """删除键。"""
        if self._redis is not None:
            self._redis.delete(key)
        else:
            self._fallback.pop(key, None)

    def acquire_lock(self, key: str, ttl: int = 7200) -> bool:
        """尝试获取互斥锁（SET NX EX）；已存在且未过期时返回 False。"""
        if self._redis is not None:
            return bool(self._redis.set(key, "1", nx=True, ex=ttl))
        entry = self._fallback.get(key)
        if entry is not None and time.time() <= entry["expires_at"]:
            return False
        self._fallback[key] = {"value": "1", "expires_at": time.time() + ttl}
        return True

    def release_lock(self, key: str) -> None:
        """释放互斥锁。"""
        self.delete(key)

    def scan_keys(self, pattern: str) -> list[str]:
        """按模式返回匹配的键（如 paper_progress:user:*）。"""
        if self._redis is not None:
            return list(self._redis.scan_iter(match=pattern))
        return [key for key in self._fallback if fnmatch.fnmatch(key, pattern)]

    # ---------- 生成进度 ----------
    def set_progress(self, user_id: str, topic: str, payload: dict, ttl: int = 86400) -> None:
        """写入生成进度。"""
        self.set(progress_key(user_id, topic), payload, ttl=ttl)

    def get_progress(self, user_id: str, topic: str) -> dict | None:
        """读取生成进度。"""
        return self.get(progress_key(user_id, topic))

    def find_active_progress(self, user_id: str) -> dict | None:
        """返回该用户最近一次任务进度（用于刷新页面恢复进度）。"""
        latest: dict | None = None
        for key in self.scan_keys(progress_key(user_id, "*")):
            payload = self.get(key)
            if not isinstance(payload, dict):
                continue
            if latest is None or payload.get("updated_at", "") > latest.get("updated_at", ""):
                latest = payload
        return latest
