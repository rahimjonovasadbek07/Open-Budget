from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# ── MAIN MENU (Reply keyboard like in screenshot) ──────────────────────────────

def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🗳 Ovoz berish"))
    builder.row(
        KeyboardButton(text="💰 Balans"),
        KeyboardButton(text="💳 Pulni yechib olish")
    )
    builder.row(KeyboardButton(text="🔗 Referal ssilka"))
    builder.row(
        KeyboardButton(text="🏆 TOP 10"),
        KeyboardButton(text="🎫 Mening ticketlarim")
    )
    builder.row(
        KeyboardButton(text="📌 Loyiha haqida"),
        KeyboardButton(text="❓ Savol-javob")
    )
    builder.row(
        KeyboardButton(text="📍 Manzil"),
        KeyboardButton(text="📞 Aloqa")
    )
    return builder.as_markup(resize_keyboard=True)


# ── VOTE ───────────────────────────────────────────────────────────────────────

def vote_kb(vote_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗳 Rasmiy saytda ovoz berish", url=vote_url))
    builder.row(InlineKeyboardButton(text="✅ Ovoz berdim", callback_data="voted_confirm"))
    return builder.as_markup()


# ── WITHDRAW ───────────────────────────────────────────────────────────────────

def withdraw_confirm_kb(amount: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"withdraw_confirm_{amount}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="withdraw_cancel"),
    )
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


# ── ADMIN ──────────────────────────────────────────────────────────────────────

def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats"),
        InlineKeyboardButton(text="🏆 Top referal", callback_data="adm_top"),
    )
    builder.row(
        InlineKeyboardButton(text="🎫 Kutayotgan ticketlar", callback_data="adm_tickets"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="adm_settings"),
    )
    return builder.as_markup()


def admin_settings_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ("✏️ Xush kelibsiz matni",   "adm_edit_welcome_text"),
        ("🎁 Ovoz bonusi (so'm)",     "adm_edit_vote_bonus"),
        ("🔗 Referal bonusi (so'm)",  "adm_edit_ref_bonus"),
        ("💸 Min yechish (so'm)",     "adm_edit_min_withdraw"),
        ("🌐 Ovoz URL",               "adm_edit_vote_url"),
        ("📢 Kanal username",         "adm_edit_channel_username"),
        ("📌 Loyiha haqida",          "adm_edit_about_text"),
        ("❓ FAQ matni",              "adm_edit_faq_text"),
        ("📞 Aloqa matni",            "adm_edit_support_username"),
        ("📍 Manzil matni",           "adm_edit_address_text"),
        ("🗺 Google Maps URL",        "adm_edit_maps_url"),
        ("🔛 Yechishni on/off",       "adm_toggle_withdraw"),
        ("🗳 Ovozni on/off",          "adm_toggle_vote"),
    ]
    for label, cb in items:
        builder.row(InlineKeyboardButton(text=label, callback_data=cb))
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="adm_menu"))
    return builder.as_markup()


def ticket_action_kb(ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash",  callback_data=f"ticket_approve_{ticket_id}"),
        InlineKeyboardButton(text="❌ Rad etish",   callback_data=f"ticket_reject_{ticket_id}"),
    )
    return builder.as_markup()


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Yuborish",     callback_data="broadcast_go"),
        InlineKeyboardButton(text="❌ Bekor",        callback_data="broadcast_no"),
    )
    return builder.as_markup()


def back_to_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Admin menyu", callback_data="adm_menu"))
    return builder.as_markup()
