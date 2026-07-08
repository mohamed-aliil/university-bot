import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Update
from aiohttp import web

from config import settings
from database.database import init_db
from database.crud import set_admin, set_permission, get_user, set_bot_active
from handlers import start, messages, admin, materials
from middlewares import ThrottlingMiddleware
from utils.logger import setup_logger

logger = logging.getLogger(__name__)
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://university-bot-8vxq.onrender.com")


async def on_startup(app: web.Application) -> None:
    bot = app["bot"]
    await init_db()
    await bot.set_webhook(f"{BASE_URL}/webhook", drop_pending_updates=True)
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


async def on_shutdown(app: web.Application) -> None:
    await app["bot"].delete_webhook()


async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def webhook_handler(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    dp = request.app["dp"]
    body = await request.read()
    update = Update.model_validate(json.loads(body), context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response(status=200)


async def main() -> None:
    setup_logger()

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

    @dp.errors()
    async def global_error(event: ErrorEvent) -> None:
        logger.exception("Unhandled error: %s", event.exception)

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_post("/webhook", webhook_handler)
    app.router.add_get("/healthz", health)

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting webhook server on port {port} …")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Bot started (webhook mode).")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
