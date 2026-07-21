from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import settings
from pathlib import Path

AI_BUTTON_HIDDEN_FILE = Path(__file__).parent.parent / "data" / ".ai_hidden"


def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="نَافِذَة التَّوَاصُل")],
        [KeyboardButton(text="نَافِذَة الـمَوَادّ")],
    ]
    if not AI_BUTTON_HIDDEN_FILE.exists():
        kb.append([KeyboardButton(text="نَافِذَة الـ AI")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def moderator_keyboard(unread_count: int = 0) -> ReplyKeyboardMarkup:
    msgs_btn = f"📩 الطلبات المرسلة ({unread_count})"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=msgs_btn)],
            [KeyboardButton(text="💬 التواصل")],
            [KeyboardButton(text="🔄 تحديث")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard(unread_count: int = 0) -> ReplyKeyboardMarkup:
    msgs_btn = f"📩 الطلبات المرسلة ({unread_count})"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 إدارة المواد")],
            [KeyboardButton(text=msgs_btn)],
            [KeyboardButton(text="💬 التواصل")],
            [KeyboardButton(text="🔄 تحديث")],
        ],
        resize_keyboard=True,
    )


def admin_kb(user_id: int, unread_count: int = 0) -> ReplyKeyboardMarkup:
    if user_id in settings.admin_ids:
        return super_admin_keyboard(unread_count=unread_count)
    return main_keyboard()


def super_admin_keyboard(unread_count: int = 0, show_admins: bool = True) -> ReplyKeyboardMarkup:
    msgs_btn = f"📩 الطلبات المرسلة ({unread_count})"
    kb = [
        [KeyboardButton(text="📚 إدارة المواد")],
        [KeyboardButton(text=msgs_btn), KeyboardButton(text="👥 الإدارة")],
        [KeyboardButton(text="💬 التواصل"), KeyboardButton(text="⚙️ الإعدادات")],
        [KeyboardButton(text="🤖 الذكاء الاصطناعي"), KeyboardButton(text="🔄 تحديث")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def admin_management_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 المشرفين"), KeyboardButton(text="📋 المستخدمين")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def communication_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 الردود السريعة"), KeyboardButton(text="📩 إرسال رسالة")],
            [KeyboardButton(text="📢 إرسال للكل")],
            [KeyboardButton(text="📰 الأخبار")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


async def news_keyboard() -> ReplyKeyboardMarkup:
    from services.news import load_templates
    templates = await load_templates()
    kb = []
    row = []
    for t in templates:
        label = t if len(t) <= 20 else t[:18] + ".."
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([KeyboardButton(text="📝 خبر مباشر")])
    kb.append([KeyboardButton(text="🔙 رجوع")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def customize_news_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة قالب"), KeyboardButton(text="➖ حذف قالب")],
            [KeyboardButton(text="📋 عرض القوالب"), KeyboardButton(text="🗑 آخر الأخبار")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def settings_keyboard(bot_active: bool = True) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="⏹ إيقاف البوت"), KeyboardButton(text="▶️ تشغيل البوت")],
        [KeyboardButton(text="🤖 إعدادات AI")],
        [KeyboardButton(text="📚 إعدادات المواد")],
        [KeyboardButton(text="📋 السجلات")],
        [KeyboardButton(text="📡 تخصيص الأخبار"), KeyboardButton(text="📡 إدارة القنوات")],
        [KeyboardButton(text="🧹 تنظيف قاعدة البيانات")],
        [KeyboardButton(text="🔄 تحديث البوت")],
        [KeyboardButton(text="🔙 رجوع")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def ai_settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏹ إيقاف AI مع إعلام"), KeyboardButton(text="🔇 إيقاف AI صامت")],
            [KeyboardButton(text="▶️ تشغيل AI")],
            [KeyboardButton(text="🙈 إخفاء الزر"), KeyboardButton(text="👁 إظهار الزر")],
            [KeyboardButton(text="📋 سجل الأخطاء")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def channels_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة قناة"), KeyboardButton(text="➖ حذف قناة")],
            [KeyboardButton(text="📋 عرض القنوات")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def materials_settings_keyboard() -> ReplyKeyboardMarkup:
    from database.crud import is_materials_active
    btn = "⏹ إيقاف المواد" if is_materials_active() else "▶️ تشغيل المواد"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=btn)],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def stop_choice_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔇 إيقاف صامت"), KeyboardButton(text="📢 إيقاف مع إعلام")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )





def admins_management_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة مشرف"), KeyboardButton(text="➖ إزالة مشرف")],
            [KeyboardButton(text="🔑 تعديل الصلاحيات")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def users_management_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 الإحصائيات")],
            [KeyboardButton(text="🔒 حظر مستخدم"), KeyboardButton(text="🔓 إلغاء حظر")],
            [KeyboardButton(text="🔍 بحث عن مستخدم"), KeyboardButton(text="🔄 إلغاء حظر الجميع")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def replies_management_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة رد"), KeyboardButton(text="➖ حذف رد")],
            [KeyboardButton(text="📋 عرض الردود")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def _truncate_cb_name(name: str, max_bytes: int = 25) -> str:
    encoded = name.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore")


def admin_reply_keyboard(user_id: int, user_full_name: str) -> InlineKeyboardMarkup:
    name = _truncate_cb_name(user_full_name, 40)
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 رد", callback_data=f"reply:{user_id}:{name}")
    builder.button(text="🚫 حظر", callback_data=f"ban:{user_id}")
    builder.button(text="⏭ عدم الرد", callback_data=f"ignore:{user_id}")
    builder.button(text="📢 للقناة", callback_data=f"forward:{user_id}:{name}")
    builder.button(text="🔇 كتم الإشعارات", callback_data=f"mute:{user_id}")
    builder.adjust(1, 2, 1, 1)
    return builder.as_markup()


def logs_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 سجلات المواد"), KeyboardButton(text="💬 سجلات الطلبات")],
            [KeyboardButton(text="📋 سجلات المستخدمين")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ إلغاء", callback_data="cancel_reply")
    return builder.as_markup()


def confirm_cleanup_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأكيد التنظيف", callback_data="confirm_cleanup")
    builder.button(text="❌ إلغاء", callback_data="cancel_cleanup")
    return builder.as_markup()


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 إدارة المشرفين", callback_data="panel:admins")
    builder.button(text="🤖 الردود السريعة", callback_data="panel:replies")
    builder.button(text="🚫 الحظر والإلغاء", callback_data="panel:bans")
    builder.button(text="📊 إحصائيات البوت", callback_data="panel:stats")
    builder.button(text="📩 إرسال رسالة", callback_data="panel:sendmsg")
    builder.button(text="🔄 تحديث البوت", callback_data="panel:restart")
    builder.button(text="🔄 تحديث", callback_data="panel:refresh")
    builder.adjust(1)
    return builder.as_markup()


def admins_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إضافة مشرف", callback_data="addadmin:start")
    builder.button(text="➖ إزالة مشرف", callback_data="removeadmin:start")
    builder.button(text="🔙 رجوع", callback_data="panel:back")
    builder.adjust(1)
    return builder.as_markup()


def replies_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إضافة رد", callback_data="addreply:start")
    builder.button(text="➖ حذف رد", callback_data="removereply:start")
    builder.button(text="🔙 رجوع", callback_data="panel:back")
    builder.adjust(1)
    return builder.as_markup()


def bans_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 إلغاء حظر الجميع", callback_data="unbanall:start")
    builder.button(text="🔙 رجوع", callback_data="panel:back")
    builder.adjust(1)
    return builder.as_markup()


def permission_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 الرد على المستخدمين", callback_data=f"perm:{user_id}:can_reply")
    builder.button(text="🚫 حظر المستخدمين", callback_data=f"perm:{user_id}:can_ban")
    builder.button(text="⚙️ إدارة الردود السريعة", callback_data=f"perm:{user_id}:can_manage")
    builder.button(text="✅ تأكيد", callback_data=f"perm:{user_id}:done")
    builder.adjust(1)
    return builder.as_markup()


def users_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔒 حظر مستخدم", callback_data="ban_user:start")
    builder.button(text="🔓 إلغاء حظر مستخدم", callback_data="unban_user:start")
    builder.button(text="🔄 إلغاء حظر الجميع", callback_data="unbanall:start")
    builder.button(text="🔙 رجوع", callback_data="panel:back")
    builder.adjust(1)
    return builder.as_markup()


def rank_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 سوبر (التحكم الكامل)", callback_data="rank:super_admin")
    builder.button(text="👑 مشرف (كل شي عدا التحكم)", callback_data="rank:admin")
    builder.button(text="🔰 مراقب (رد + ردود سريعة)", callback_data="rank:moderator")
    builder.adjust(1)
    return builder.as_markup()


def confirm_send_keyboard(unique_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ إرسال", callback_data=f"confirm_send:yes:{unique_id}")
    builder.button(text="❌ إلغاء", callback_data=f"confirm_send:no:{unique_id}")
    builder.adjust(2)
    return builder.as_markup()


def review_reply_keyboard(muted: bool = False, has_prev: bool = False, has_next: bool = False) -> ReplyKeyboardMarkup:
    kb = []
    nav_row = []
    if has_next:
        nav_row.append(KeyboardButton(text="➡️ التالي"))
    if has_prev:
        nav_row.append(KeyboardButton(text="⬅️ السابق"))
    if nav_row:
        kb.append(nav_row)
    mute_text = "🔔 تشغيل الإشعارات" if muted else "🔇 إيقاف الإشعارات"
    kb.append([KeyboardButton(text=mute_text)])
    kb.append([KeyboardButton(text="🔙 رجوع")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def message_review_keyboard(msg_id: int, user_id: int, user_name: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 رد", callback_data=f"review_reply:{msg_id}:{user_id}")
    builder.button(text="🗑 حذف", callback_data=f"review_delete:{msg_id}")
    builder.adjust(2)
    return builder.as_markup()


async def quick_reply_inline_keyboard(user_id: int, user_name: str) -> InlineKeyboardMarkup:
    from database.crud import get_all_autoreplies
    replies = await get_all_autoreplies()
    name = _truncate_cb_name(user_name, 35)
    builder = InlineKeyboardBuilder()
    for ar in replies[:8]:
        label = ar.trigger if len(ar.trigger) <= 25 else ar.trigger[:22] + "..."
        builder.button(text=label, callback_data=f"quick_reply:{ar.id}:{user_id}:{name}")
    builder.button(text="✏️ رد مخصص", callback_data=f"custom_reply:{user_id}:{name}")
    builder.adjust(1)
    return builder.as_markup()


async def quick_reply_keyboard() -> ReplyKeyboardMarkup:
    from database.crud import get_all_autoreplies
    replies = await get_all_autoreplies()
    kb = []
    row = []
    for i, ar in enumerate(replies[:10]):
        label = ar.trigger if len(ar.trigger) <= 20 else ar.trigger[:18] + ".."
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([KeyboardButton(text="✏️ رد مخصص"), KeyboardButton(text="❌ إلغاء")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def ai_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة سؤال/جواب"), KeyboardButton(text="➖ حذف سؤال/جواب")],
            [KeyboardButton(text="📋 عرض الأسئلة"), KeyboardButton(text="📄 رفع ملف سياق")],
            [KeyboardButton(text="📰 إضافة مقال"), KeyboardButton(text="📋 عرض المقالات")],
            [KeyboardButton(text="🔗 المتطلبات الدراسية"), KeyboardButton(text="🧠 تحليل صورة")],
            [KeyboardButton(text="🤖 محادثة ذكية"), KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def ai_user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def agreement_keyboard() -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ موافقة", callback_data="agree_ai")
    builder.button(text="❌ عدم الموافقة", callback_data="disagree_ai")
    builder.adjust(2)
    return builder.as_markup()



