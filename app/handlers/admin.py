import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from loguru import logger

from app.keyboards import (
    admin_menu_kb, admin_settings_kb,
    ticket_action_kb, confirm_broadcast_kb, back_to_admin_kb
)
from database import repository
from config import settings

router = Router(name="admin")


def is_admin(uid: int) -> bool:
    return uid in settings.admin_ids_list


# ── FSM ────────────────────────────────────────────────────────────────────────

class BroadcastState(StatesGroup):
    waiting_msg = State()
    confirming  = State()

class EditSettingState(StatesGroup):
    waiting_val = State()

class AddBalanceState(StatesGroup):
    waiting_data = State()


# ── /admin ─────────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ruxsat yo'q.")
        return
    await message.answer("🔧 <b>Admin Panel</b>", parse_mode="HTML",
                         reply_markup=admin_menu_kb())


@router.callback_query(F.data == "adm_menu")
async def cb_adm_menu(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    await state.clear()
    await call.message.edit_text("🔧 <b>Admin Panel</b>", parse_mode="HTML",
                                  reply_markup=admin_menu_kb())
    await call.answer()


# ── STATISTIKA ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_stats")
async def cb_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    total    = await repository.get_total_users()
    tickets  = await repository.get_pending_tickets()
    text = (
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total}</b>\n"
        f"🎫 Kutayotgan ticketlar: <b>{len(tickets)}</b>\n"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    await call.answer()


# ── TOP REFERALLAR ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_top")
async def cb_top(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    top    = await repository.get_top_referrers(10)
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    lines  = ["🏆 <b>Top referalchilar</b>\n"]
    for i, row in enumerate(top):
        if row["ref_count"] == 0: continue
        name  = row["first_name"] or "Nomsiz"
        uname = f"@{row['username']}" if row["username"] else f"ID:{row['telegram_id']}"
        lines.append(f"{medals[i]} {name} ({uname}) — <b>{row['ref_count']}</b>")
    if len(lines) == 1:
        lines.append("Hali yo'q.")
    await call.message.edit_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=admin_menu_kb())
    await call.answer()


# ── TICKETLAR ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_tickets")
async def cb_tickets(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    tickets = await repository.get_pending_tickets()
    if not tickets:
        await call.message.edit_text("✅ Kutayotgan ticket yo'q.",
                                      reply_markup=admin_menu_kb())
        await call.answer(); return

    for t in tickets:
        name   = t["first_name"] or "Nomsiz"
        uname  = f"@{t['username']}" if t["username"] else f"ID:{t['user_id']}"
        card   = t["card_number"] or ""
        masked = f"{card[:4]} **** **** {card[-4:]}" if len(card) >= 8 else card
        date   = t["created_at"].strftime("%d.%m.%Y %H:%M")
        text   = (
            f"🎫 <b>Ticket #{t['id']}</b>\n\n"
            f"👤 {name} ({uname})\n"
            f"💵 Miqdor: <b>{t['amount']:,} so'm</b>\n"
            f"💳 Karta: <b>{masked}</b>\n"
            f"📅 Sana: {date}"
        )
        await call.message.answer(text, parse_mode="HTML",
                                   reply_markup=ticket_action_kb(t["id"]))

    await call.message.edit_text(f"🎫 {len(tickets)} ta ticket ko'rsatildi.",
                                  reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data.startswith("ticket_approve_"))
async def cb_approve(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    ticket_id = int(call.data.split("_")[-1])
    ticket    = await repository.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Ticket topilmadi!", show_alert=True); return
    await repository.update_ticket_status(ticket_id, "approved")
    await call.message.edit_text(
        f"✅ Ticket #{ticket_id} tasdiqlandi!\n💵 {ticket['amount']:,} so'm"
    )
    try:
        await bot.send_message(
            ticket["user_id"],
            f"✅ <b>To'lov tasdiqlandi!</b>\n\n"
            f"🎫 Ticket #{ticket_id}\n"
            f"💵 {ticket['amount']:,} so'm\n"
            f"💳 {ticket['card_number'][:4]}**** **** {ticket['card_number'][-4:]}\n\n"
            f"Pul 24 soat ichida kartangizga tushadi.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer("✅ Tasdiqlandi!")


@router.callback_query(F.data.startswith("ticket_reject_"))
async def cb_reject(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    ticket_id = int(call.data.split("_")[-1])
    ticket    = await repository.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Ticket topilmadi!", show_alert=True); return
    await repository.update_ticket_status(ticket_id, "rejected")
    # Refund balance
    await repository.add_balance(ticket["user_id"], ticket["amount"])
    await call.message.edit_text(
        f"❌ Ticket #{ticket_id} rad etildi. Balans qaytarildi."
    )
    try:
        await bot.send_message(
            ticket["user_id"],
            f"❌ <b>To'lov rad etildi.</b>\n\n"
            f"🎫 Ticket #{ticket_id}\n"
            f"💵 {ticket['amount']:,} so'm balansingizga qaytarildi.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer("❌ Rad etildi!")


# ── BROADCAST ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    await state.set_state(BroadcastState.waiting_msg)
    await call.message.edit_text(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:\n"
        "<i>HTML formatdan foydalanishingiz mumkin</i>",
        parse_mode="HTML", reply_markup=back_to_admin_kb()
    )
    await call.answer()


@router.message(BroadcastState.waiting_msg)
async def process_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(text=message.text or "")
    await state.set_state(BroadcastState.confirming)
    total = await repository.get_total_users()
    await message.answer(
        f"📋 <b>Ko'rinish:</b>\n\n{message.text}\n\n"
        f"👥 {total} ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
        parse_mode="HTML", reply_markup=confirm_broadcast_kb()
    )


@router.callback_query(F.data == "broadcast_go")
async def cb_broadcast_go(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    data = await state.get_data()
    text = data.get("text", "")
    await state.clear()
    await call.message.edit_text("⏳ Yuborilmoqda...")
    await call.answer()

    ids = await repository.get_all_user_ids()
    sent = failed = blocked = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            if "blocked" in str(e).lower() or "403" in str(e):
                await repository.mark_blocked(uid)
                blocked += 1
            else:
                failed += 1
        await asyncio.sleep(0.05)

    await call.message.edit_text(
        f"✅ <b>Broadcast tugadi!</b>\n\n"
        f"📤 Yuborildi: <b>{sent}</b>\n"
        f"🚫 Bloklaganlar: <b>{blocked}</b>\n"
        f"❌ Xatolik: <b>{failed}</b>",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )


@router.callback_query(F.data == "broadcast_no")
async def cb_broadcast_no(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.", reply_markup=admin_menu_kb())
    await call.answer()


# ── SOZLAMALAR ─────────────────────────────────────────────────────────────────

SETTING_MAP = {
    "adm_edit_welcome_text":      ("welcome_text",      "Xush kelibsiz matni"),
    "adm_edit_vote_bonus":        ("vote_bonus",        "Ovoz bonusi (faqat raqam)"),
    "adm_edit_ref_bonus":         ("ref_bonus",         "Referal bonusi (faqat raqam)"),
    "adm_edit_min_withdraw":      ("min_withdraw",      "Minimal yechish (faqat raqam)"),
    "adm_edit_vote_url":          ("vote_url",          "Ovoz berish URL"),
    "adm_edit_channel_username":  ("channel_username",  "Kanal username (@bilan)"),
    "adm_edit_about_text":        ("about_text",        "Loyiha haqida matni"),
    "adm_edit_faq_text":          ("faq_text",          "FAQ matni"),
    "adm_edit_support_username":  ("support_username",  "Yordam username (@bilan)"),
    "adm_edit_address_text":      ("address_text",      "Manzil matni"),
    "adm_edit_maps_url":          ("maps_url",          "Google Maps URL"),
}


@router.callback_query(F.data == "adm_settings")
async def cb_settings(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    await call.message.edit_text("⚙️ <b>Sozlamalar</b>\n\nNimani o'zgartirmoqchisiz?",
                                  parse_mode="HTML", reply_markup=admin_settings_kb())
    await call.answer()


@router.callback_query(F.data.in_(SETTING_MAP.keys()))
async def cb_edit_setting(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    key, label = SETTING_MAP[call.data]
    current    = await repository.get_setting(key) or "—"
    await state.set_state(EditSettingState.waiting_val)
    await state.update_data(setting_key=key)
    await call.message.edit_text(
        f"✏️ <b>{label}</b>\n\n"
        f"Hozirgi qiymat:\n<code>{current[:300]}</code>\n\n"
        f"Yangi qiymatni yozing:",
        parse_mode="HTML", reply_markup=back_to_admin_kb()
    )
    await call.answer()


@router.message(EditSettingState.waiting_val)
async def process_setting_val(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    key  = data.get("setting_key")
    val  = message.text or ""
    if key and val:
        await repository.set_setting(key, val)
        await state.clear()
        await message.answer(f"✅ <b>{key}</b> yangilandi!",
                              parse_mode="HTML", reply_markup=admin_menu_kb())
    else:
        await message.answer("❌ Qiymat kiritilmadi.")


# ── TOGGLE ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_toggle_withdraw")
async def cb_toggle_withdraw(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    cur = await repository.get_setting("withdraw_enabled") or "true"
    new = "false" if cur.lower() == "true" else "true"
    await repository.set_setting("withdraw_enabled", new)
    status = "✅ Yoqildi" if new == "true" else "⏸ O'chirildi"
    await call.answer(f"Yechish: {status}", show_alert=True)


@router.callback_query(F.data == "adm_toggle_vote")
async def cb_toggle_vote(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️", show_alert=True); return
    cur = await repository.get_setting("vote_enabled") or "true"
    new = "false" if cur.lower() == "true" else "true"
    await repository.set_setting("vote_enabled", new)
    status = "✅ Yoqildi" if new == "true" else "⏸ O'chirildi"
    await call.answer(f"Ovoz berish: {status}", show_alert=True)


# ── /addbalance ─────────────────────────────────────────────────────────────────

@router.message(Command("addbalance"))
async def cmd_add_balance(message: Message):
    """Usage: /addbalance <user_id> <amount>"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ruxsat yo'q."); return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Foydalanish: /addbalance <user_id> <miqdor>"); return
    try:
        uid    = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("❌ Noto'g'ri formatr!"); return
    new_bal = await repository.add_balance(uid, amount)
    await message.answer(
        f"✅ Foydalanuvchi {uid} ga {amount:,} so'm qo'shildi.\n"
        f"💵 Yangi balans: {new_bal:,} so'm"
    )


# ── /cancel ─────────────────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.")
