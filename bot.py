import asyncio
import json
import logging
import os
import time as _time
import traceback

from services.gemini import LAST_AI_MS

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ErrorEvent, Update, CallbackQuery
from aiogram.filters import CommandStart
from aiohttp import web

from config import settings
from database.database import init_db
from database.crud import set_admin, set_permission, get_user, set_bot_active, set_materials_active, is_admin_user, get_all_required_channels, set_channel_verified, save_error_db
from handlers import start, messages, admin, materials, channels, ai
from middlewares import ThrottlingMiddleware, SubscriptionMiddleware, BotActiveMiddleware
from utils.logger import setup_logger
from keyboards.reply import main_keyboard

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
    _t0 = _time.perf_counter()
    bot = request.app["bot"]
    dp = request.app["dp"]
    update: Update | None = None
    try:
        body = await request.read()
        update = Update.model_validate(json.loads(body))
    except Exception as e:
        logger.exception("Webhook parse error: %s", e)
        return web.Response(status=200)

    app = request.app
    asyncio.create_task(process_update(app, bot, dp, update, _t0))
    return web.Response(status=200)


_chat_locks: dict[int, asyncio.Lock] = {}
_chat_locks_guard = asyncio.Lock()

# Slow-update watchdog: reports to admins + error log when an update takes too long
_SLOW_MS = 3000
_last_slow_report: float = 0.0
_slow_report_interval = 60.0  # seconds between admin notifications


def _update_summary(update: Update) -> str:
    if update.message:
        m = update.message
        who = (m.from_user.full_name or m.from_user.username or str(m.from_user.id)) if m.from_user else "?"
        uid = m.from_user.id if m.from_user else "?"
        txt = (m.text or m.caption or "")[:60]
        return f"رسالة من {who} (id:{uid}, chat:{m.chat.id}): {txt or m.content_type}"
    if update.callback_query:
        c = update.callback_query
        who = (c.from_user.full_name or c.from_user.username or str(c.from_user.id)) if c.from_user else "?"
        uid = c.from_user.id if c.from_user else "?"
        return f"زر من {who} (id:{uid}): {c.data or ''}"
    if update.channel_post:
        return f"منشور قناة: {(update.channel_post.text or '')[:60]}"
    return update.model_dump(exclude_none=True)


def _update_meta(update: Update) -> dict:
    meta = {"update_type": "unknown", "content_preview": "", "text": ""}
    if update.message:
        m = update.message
        meta["update_type"] = "message"
        meta["user_id"] = m.from_user.id if m.from_user else None
        meta["chat_id"] = m.chat.id
        meta["content"] = (m.text or m.caption or "")[:120] or m.content_type
    elif update.callback_query:
        c = update.callback_query
        meta["update_type"] = "callback_query"
        meta["user_id"] = c.from_user.id if c.from_user else None
        meta["chat_id"] = c.message.chat.id if c.message else None
        meta["content"] = (c.data or "")[:120]
    elif update.channel_post:
        meta["update_type"] = "channel_post"
        meta["chat_id"] = update.channel_post.chat.id
        meta["content"] = (update.channel_post.text or "")[:60]
    return meta


def _slow_detail(update: Update, ms: float, ai_ms: float, ai_model: str) -> str:
    meta = _update_meta(update)
    detail = f"بطء {ms:.0f}ms ({meta['update_type']}, user={meta.get('user_id')}, chat={meta.get('chat_id')}): {meta['content']}"
    if ai_ms > 0:
        share = ai_ms / ms * 100 if ms > 0 else 0
        detail += f"\n◾ مرحلة النموذج: {ai_ms:.0f}ms = {share:.0f}% من الزمن (النموذج: {ai_model})"
        if share > 50:
            detail += f"\n◾ التحليل: المسبب الرئيسي هو استجابة نموذج AI ({ai_ms:.0f}ms). باقي المعالجة {max(0.0, ms - ai_ms):.0f}ms فقط."
    else:
        detail += "\n◾ مرحلة النموذج: لم يُستدعَ AI"
        detail += "\n◾ التحليل: المسبب الرئيسي هو قاعدة البيانات/المعالجة البرمجية (استعلامات متسلسلة أو تحميل سيرفر)."
    detail += "\n\nTECH_JSON: " + json.dumps({
        "code": "SLOW_UPDATE",
        "total_ms": round(ms, 1),
        "ai_ms": round(ai_ms, 1),
        "ai_model": ai_model,
        **meta,
    }, ensure_ascii=False)
    return detail


async def _notify_admins(bot, text: str) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode=None)
        except Exception:
            pass


async def _report_slow(bot, update, ms: float, ai_ms: float, ai_model: str) -> None:
    global _last_slow_report
    detail = _slow_detail(update, ms, ai_ms, ai_model)
    try:
        await save_error_db("SLOW_UPDATE", detail, user_id=_update_meta(update).get("user_id"))
    except Exception:
        pass
    now = _time.monotonic()
    if now - _last_slow_report < _slow_report_interval:
        return
    _last_slow_report = now
    await _notify_admins(
        bot,
        f"⚠️ بطء في معالجة تحديث ({ms:.0f}ms)\n\n{detail}\n\n"
        f"حدّ البطء: {_SLOW_MS}ms. تفاصيل إضافية في سجل الأخطاء.",
    )


def _get_chat_lock(update: Update) -> asyncio.Lock:
    chat_id: int | None = None
    if update.message:
        chat_id = update.message.chat.id
    elif update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat.id
    if chat_id is None:
        return None
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


async def process_update(app, bot, dp, update, _t0) -> None:
    lock = _get_chat_lock(update)
    if lock is None:
        try:
            await dp.feed_update(bot, update)
        except Exception as e:
            logger.exception("Webhook error: %s", e)
            await _report_error(bot, update, e)
        return
    async with lock:
        try:
            ai_before = LAST_AI_MS.get("ms", 0.0)
            await dp.feed_update(bot, update)
            ms = (_time.perf_counter() - _t0) * 1000
            ai_after = LAST_AI_MS.get("ms", 0.0)
            ai_ms = ai_after - ai_before
            if ai_ms < 0 or ai_ms > ms:
                ai_ms = ai_after
            ai_model = LAST_AI_MS.get("model", "?")
            logger.info("webhook update processed in %.0fms (AI: %.0fms, %s)", ms, ai_ms, ai_model)
            if ms > _SLOW_MS:
                await _report_slow(bot, update, ms, ai_ms, ai_model)
        except Exception as e:
            logger.exception("Webhook error: %s", e)
            await _report_error(bot, update, e)


async def _report_error(bot, update, e: Exception) -> None:
    try:
        from database.crud import save_error_db
        meta = _update_meta(update)
        detail = (
            f"❌ {e}\n\n"
            f"{_update_summary(update)}\n\nTECH_JSON: " + json.dumps(meta, ensure_ascii=False)
        )
        await save_error_db(
            "webhook",
            detail[:2000],
            user_id=meta.get("user_id"),
            traceback=traceback.format_exc()[:3000],
        )
    except Exception:
        pass
    await _notify_admins(
        bot,
        f"❌ خطأ أثناء معالجة تحديث:\n{e}\n\n{_update_summary(update)}\n\n"
        f"انظر سجل الأخطاء للتفاصيل الكاملة.",
    )


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
    dp.include_router(ai.router)
    dp.include_router(messages.router)
    dp.include_router(channels.channel_router)
    dp.message.middleware(BotActiveMiddleware())
    dp.callback_query.middleware(BotActiveMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.25))

    @dp.callback_query(lambda c: c.data == "verify_subscription")
    async def verify_subscription_callback(callback: CallbackQuery) -> None:
        user = callback.from_user
        channels = await get_all_required_channels()
        if not channels:
            await callback.message.edit_text("❌ لا توجد قنوات مطلوبة حالياً.")
            await callback.answer()
            return

        pending = []
        for ch in channels:
            try:
                member = await bot.get_chat_member(ch.chat_id, user.id)
                if member.status in ("member", "creator", "administrator"):
                    continue
            except Exception:
                pass
            pending.append(ch)

        if not pending:
            await set_channel_verified(user.id)
            await callback.message.edit_text(
                "✅ تم التحقق من اشتراكك في جميع القنوات!\nأرسل /start للبدء."
            )
            await callback.answer()
            return

        # Still not subscribed to some
        first = pending[0]
        link = first.invite_link or first.chat_id
        builder = InlineKeyboardBuilder()
        builder.button(text="لقد اشتركت", callback_data="verify_subscription")
        if first.invite_link and first.invite_link.startswith("http"):
            builder.button(text="📢 اضغط للاشتراك", url=first.invite_link)
        builder.adjust(1)
        await callback.message.edit_text(
            f"❌ لم تشترك في القناة التالية بعد:\n\n{link}",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()

    @dp.errors()
    async def global_error(event: ErrorEvent) -> None:
        tb = traceback.format_exception(type(event.exception), event.exception, event.exception.__traceback__)
        tb_str = "".join(tb[-5:])
        logger.exception("Unhandled error: %s", event.exception)
        try:
            from database.crud import save_error_db
            user_id = None
            if event.update and event.update.message:
                user_id = event.update.message.from_user.id
            elif event.update and event.update.callback_query:
                user_id = event.update.callback_query.from_user.id
            await save_error_db("global", str(event.exception)[:500], user_id=user_id, traceback=tb_str[:3000])
        except Exception:
            pass
        try:
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
