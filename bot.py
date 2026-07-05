import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import settings
from database.database import init_db
from database.crud import set_admin, set_permission, get_user, set_bot_active
from handlers import start, messages, admin
from middlewares import ThrottlingMiddleware
from utils.logger import setup_logger

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "botkey-secret-2026"


async def on_startup(bot: Bot) -> None:
    await init_db()
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
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if webhook_url:
        await bot.set_webhook(
            url=f"{webhook_url}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            allowed_updates=["message", "callback_query"],
        )
        logger.info(f"Webhook set to {webhook_url}{WEBHOOK_PATH}")
    logger.info("Bot ready.")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot shutting down...")


async def main_polling() -> None:
    setup_logger()
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(messages.router)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))
    dp.startup.register(on_startup)
    logger.info("Bot started polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def main_webhook() -> None:
    setup_logger()
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(messages.router)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting webhook on port {port}...")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    if os.environ.get("RENDER_EXTERNAL_URL"):
        main_webhook()
    else:
        try:
            asyncio.run(main_polling())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot stopped.")
