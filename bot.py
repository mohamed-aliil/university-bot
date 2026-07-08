import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.types import ErrorEvent
from aiohttp import web

from config import settings
from database.database import init_db
from database.crud import set_admin, set_permission, get_user, set_bot_active
from handlers import start, messages, admin, materials
from middlewares import ThrottlingMiddleware
from utils.logger import setup_logger

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    set_bot_active(True)
    for aid in settings.admin_ids:
        user = await get_user(aid)
        if user:
            await set_admin(aid, True, rank="super_admin")
            await set_permission(aid, "can_reply", True)
            await set_permission(aid, "can_ban", True)
            await set_permission(aid, "can_manage", True)
            await set_permission(aid, "can_view_logs", True)
            await set_permission(aid, "can_control_bot", True)
    logger.info("Bot ready.")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def run_web():
    app = web.Application()
    app.router.add_get("/healthz", health)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server running on port {port}")


async def main() -> None:
    setup_logger()
    await asyncio.sleep(5)
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(materials.router)
    dp.include_router(messages.router)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))
    dp.startup.register(on_startup)

    @dp.errors()
    async def global_error(event: ErrorEvent) -> None:
        logger.exception("Unhandled error: %s", event.exception)

    await run_web()
    logger.info("Bot started polling...")
    polling_kwargs = dict(allowed_updates=dp.resolve_used_update_types())
    while True:
        try:
            await dp.start_polling(bot, **polling_kwargs)
            break
        except TelegramConflictError:
            logger.warning("تعارض polling — ننتظر 10 ثوانٍ ونحاول مجدداً…")
            await asyncio.sleep(10)
        except Exception as e:
            logger.exception("خطأ غير متوقع في polling: %s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
