import sys
from loguru import logger
from config import settings

def setup_logging():
    logger.remove()
    fmt = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
    logger.add(sys.stdout, format=fmt, level=settings.LOG_LEVEL, colorize=True)
    logger.add("logs/bot_{time:YYYY-MM-DD}.log", format=fmt, level="DEBUG",
               rotation="00:00", retention="30 days", compression="gz", encoding="utf-8")
    logger.info(f"📝 Logging ready | {settings.ENVIRONMENT}")
