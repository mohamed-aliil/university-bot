import asyncio
import json
import logging
import os
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Update
from aiohttp import web

from config import settings
from database.database import init_db
from database.crud import set_admin, set_permission, get_user, set_bot_active, set_materials_active, is_admin_user
from handlers import start, messages, admin, materials, channels, ai
from middlewares import ThrottlingMiddleware
from utils.logger import setup_logger

logger = logging.getLogger(__name__)
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://university-bot-8vxq.onrender.com")


async def on_startup(app: web.Application) -> None:
    bot = app["bot"]
    await init_db()
    await bot.set_webhook(f"{BASE_URL}/webhook", drop_pending_updates=True)
    set_bot_active(True)
    set_materials_active(True)
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
    try:
        body = await request.read()
        update = Update.model_validate(json.loads(body))
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.exception("Webhook error: %s", e)
    return web.Response(status=200)


async def main() -> None:
    setup_logger()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(channels.router)
    dp.include_router(materials.router)
    dp.include_router(admin.router)
    dp.include_router(messages.router)
    dp.include_router(ai.router)
    dp.include_router(channels.channel_router)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))

    @dp.errors()
    async def global_error(event: ErrorEvent) -> None:
        tb = traceback.format_exception(type(event.exception), event.exception, event.exception.__traceback__)
        tb_str = "".join(tb[-5:])
        logger.exception("Unhandled error: %s", event.exception)
        try:
            user_id = None
            if event.update and event.update.message:
                user_id = event.update.message.from_user.id
            elif event.update and event.update.callback_query:
                user_id = event.update.callback_query.from_user.id
            if user_id and (user_id in settings.admin_ids or await is_admin_user(user_id)):
                msg = f"⚠️ خطأ:\n\n<code>{tb_str[:2000]}</code>"
            else:
                msg = "⚠️ عذراً، حدث خطأ داخلي. يرجى المحاولة لاحقاً."
            if event.update and event.update.message:
                await event.update.message.answer(msg)
            elif event.update and event.update.callback_query:
                await event.update.callback_query.message.answer(msg)
        except Exception:
            pass

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
