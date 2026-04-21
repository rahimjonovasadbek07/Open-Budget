import asyncpg
from loguru import logger
from config import settings

_pool = None

async def create_pool():
    global _pool
    _pool = await asyncpg.create_pool(dsn=settings.db_dsn, min_size=2, max_size=10)
    logger.info("✅ Database pool created")
    return _pool

async def get_pool():
    if _pool is None:
        raise RuntimeError("Pool not initialized")
    return _pool

async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("🔌 Database pool closed")
