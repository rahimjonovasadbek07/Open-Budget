import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from app import setup_routers, RateLimitMiddleware, setup_logging
from config import settings
from database import create_pool, close_pool, run_migrations
from database.migrations import add_otp_sessions_table


async def on_startup(bot: Bot):
    pool = await create_pool()
    await run_migrations(pool)
    await add_otp_sessions_table(pool)
    info = await bot.get_me()
    logger.info(f"🤖 @{info.username} started | Admins: {settings.admin_ids_list}")
    if settings.use_webhook:
        await bot.set_webhook(f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}")
        logger.info("🔗 Webhook set")
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🔄 Polling mode")
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id,
                f"✅ <b>Bot ishga tushdi!</b>\n🤖 @{info.username}",
                parse_mode="HTML")
        except Exception:
            pass


async def on_shutdown(bot: Bot):
    logger.info("🛑 Shutting down...")
    await close_pool()
    if settings.use_webhook:
        await bot.delete_webhook()


async def main():
    setup_logging()
    bot = Bot(token=settings.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.message.middleware(RateLimitMiddleware())
    dp.include_router(setup_routers())

    if settings.use_webhook:
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host=settings.APP_HOST, port=settings.APP_PORT)
    else:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopped")
    except Exception as e:
        logger.critical(f"💥 Fatal: {e}")
        sys.exit(1)
