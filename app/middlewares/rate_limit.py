from typing import Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from cachetools import TTLCache
from loguru import logger
from config import settings


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self):
        self._cache: TTLCache = TTLCache(maxsize=10_000, ttl=60)
        self._warned: TTLCache = TTLCache(maxsize=10_000, ttl=60)

    async def __call__(self, handler: Callable, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        user_id = event.from_user.id if event.from_user else None
        if not user_id or user_id in settings.admin_ids_list:
            return await handler(event, data)
        count = self._cache.get(user_id, 0) + 1
        self._cache[user_id] = count
        if count > 10:
            if user_id not in self._warned:
                self._warned[user_id] = True
                await event.answer("⏳ Biroz kuting...")
            return
        return await handler(event, data)
