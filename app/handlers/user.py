from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from loguru import logger

from app.keyboards import (
    main_menu_kb, vote_kb, withdraw_confirm_kb, cancel_kb
)
from database import repository

router = Router(name="user")


class WithdrawStates(StatesGroup):
    waiting_amount = State()
    waiting_card   = State()


# ── HELPERS ────────────────────────────────────────────────────────────────────

async def register_user(tg_user, referrer_id=None):
    if referrer_id == tg_user.id:
        referrer_id = None
    existing = await repository.get_user(tg_user.id)
    is_new = existing is None
    valid_ref = None
    if is_new and referrer_id:
        ref = await repository.get_user(referrer_id)
        if ref:
            valid_ref = referrer_id
    record, _ = await repository.get_or_create_user(
        tg_user.id, tg_user.first_name or "", tg_user.last_name,
        tg_user.username, valid_ref
    )
    if is_new and valid_ref:
        await repository.create_referral(valid_ref, tg_user.id)
        ref_bonus = int(await repository.get_setting("ref_bonus") or "10000")
        await repository.add_balance(valid_ref, ref_bonus)
    return record, is_new


async def fmt_sum(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


# ── /start ─────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    referrer_id = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
        except ValueError:
            pass

    user, is_new = await register_user(message.from_user, referrer_id)

    vote_bonus = await repository.get_setting("vote_bonus") or "30000"
    ref_bonus  = await repository.get_setting("ref_bonus")  or "10000"

    welcome_tpl = await repository.get_setting("welcome_text") or (
        "Botga xush kelibsiz!\n\n"
        "🎁 Har bir ovozga <b>{vote_bonus} so'm</b> oling!\n"
        "🔗 Odam chaqirganiz uchun <b>{ref_bonus} so'm</b> beriladi"
    )
    welcome = welcome_tpl.replace("{vote_bonus}", vote_bonus).replace("{ref_bonus}", ref_bonus)

    name = message.from_user.first_name
    text = f"{name} 👋 {welcome}"

    if is_new and referrer_id:
        try:
            ref_user = await repository.get_user(referrer_id)
            if ref_user:
                await bot.send_message(
                    referrer_id,
                    f"🎉 Siz orqali <b>{name}</b> qo'shildi!\n"
                    f"💰 Hisobingizga <b>{ref_bonus} so'm</b> qo'shildi!",
                    parse_mode="HTML"
                )
        except Exception:
            pass

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


# ── OVOZ BERISH ────────────────────────────────────────────────────────────────

@router.message(F.text == "🗳 Ovoz berish")
async def btn_vote(message: Message):
    vote_enabled = await repository.get_setting("vote_enabled") or "true"
    if vote_enabled.lower() != "true":
        await message.answer("⏸ Ovoz berish hozircha to'xtatilgan.")
        return

    vote_url   = await repository.get_setting("vote_url")   or "https://openbudget.uz"
    vote_bonus = await repository.get_setting("vote_bonus") or "30000"

    text = (
        f"🗳 <b>Ovoz berish</b>\n\n"
        f"Rasmiy saytda ovoz bering va <b>{vote_bonus} so'm</b> oling!\n\n"
        f"⚠️ Ovoz berganingizdan so'ng '✅ Ovoz berdim' tugmasini bosing."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=vote_kb(vote_url))


@router.callback_query(F.data == "voted_confirm")
async def cb_voted(call: CallbackQuery):
    vote_bonus = int(await repository.get_setting("vote_bonus") or "30000")
    new_balance = await repository.add_balance(call.from_user.id, vote_bonus)
    await call.message.edit_text(
        f"✅ <b>Rahmat!</b> Ovoz uchun hisobingizga "
        f"<b>{vote_bonus:,} so'm</b> qo'shildi!\n\n"
        f"💰 Joriy balans: <b>{new_balance:,} so'm</b>",
        parse_mode="HTML"
    )
    await call.answer("✅ Bonus qo'shildi!")


# ── BALANS ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "💰 Balans")
async def btn_balance(message: Message, bot: Bot):
    user = await repository.get_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start bosing.")
        return
    ref_count = await repository.get_referral_count(message.from_user.id)
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    min_w = await repository.get_setting("min_withdraw") or "50000"

    text = (
        f"💰 <b>Balans ma'lumotlari</b>\n\n"
        f"👤 Ism: {user['first_name']}\n"
        f"💵 Balans: <b>{user['balance']:,} so'm</b>\n"
        f"👥 Referallar: <b>{ref_count} ta</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{ref_link}</code>\n\n"
        f"💡 Minimal yechish: {int(min_w):,} so'm"
    )
    await message.answer(text, parse_mode="HTML")


# ── PULNI YECHIB OLISH ─────────────────────────────────────────────────────────

@router.message(F.text == "💳 Pulni yechib olish")
async def btn_withdraw(message: Message, state: FSMContext):
    withdraw_enabled = await repository.get_setting("withdraw_enabled") or "true"
    if withdraw_enabled.lower() != "true":
        await message.answer("⏸ Yechib olish hozircha to'xtatilgan.")
        return

    user = await repository.get_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start bosing.")
        return

    min_w = int(await repository.get_setting("min_withdraw") or "50000")
    if user["balance"] < min_w:
        await message.answer(
            f"❌ Balansingiz yetarli emas!\n\n"
            f"💵 Balans: <b>{user['balance']:,} so'm</b>\n"
            f"📌 Minimal: <b>{min_w:,} so'm</b>",
            parse_mode="HTML"
        )
        return

    await state.set_state(WithdrawStates.waiting_amount)
    await message.answer(
        f"💳 <b>Pul yechib olish</b>\n\n"
        f"💵 Balansingiz: <b>{user['balance']:,} so'm</b>\n"
        f"📌 Minimal: <b>{min_w:,} so'm</b>\n\n"
        f"Qancha yechib olmoqchisiz? (raqam kiriting)",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(WithdrawStates.waiting_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("❌ Faqat raqam kiriting!")
        return

    user  = await repository.get_user(message.from_user.id)
    min_w = int(await repository.get_setting("min_withdraw") or "50000")

    if amount < min_w:
        await message.answer(f"❌ Minimal {min_w:,} so'm!")
        return
    if amount > user["balance"]:
        await message.answer(f"❌ Balansingizdan ko'p! (Balans: {user['balance']:,} so'm)")
        return

    await state.update_data(amount=amount)
    await state.set_state(WithdrawStates.waiting_card)
    await message.answer(
        f"💳 Karta raqamingizni kiriting:\n(16 ta raqam, masalan: 8600 1234 5678 9012)",
        reply_markup=cancel_kb()
    )


@router.message(WithdrawStates.waiting_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    card = message.text.replace(" ", "")
    if not card.isdigit() or len(card) < 16:
        await message.answer("❌ Noto'g'ri karta raqami! 16 ta raqam kiriting.")
        return

    data   = await state.get_data()
    amount = data["amount"]

    # Deduct balance and create ticket
    success = await repository.deduct_balance(message.from_user.id, amount)
    if not success:
        await state.clear()
        await message.answer("❌ Balans yetarli emas!")
        return

    ticket = await repository.create_ticket(message.from_user.id, amount, card)
    await state.clear()

    await message.answer(
        f"✅ <b>So'rov yuborildi!</b>\n\n"
        f"🎫 Ticket #{ticket['id']}\n"
        f"💵 Miqdor: <b>{amount:,} so'm</b>\n"
        f"💳 Karta: <b>{card[:4]} **** **** {card[-4:]}</b>\n\n"
        f"⏳ Admin tasdiqlashini kuting (24 soat ichida)",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()


# ── REFERAL ────────────────────────────────────────────────────────────────────

@router.message(F.text == "🔗 Referal ssilka")
async def btn_referral(message: Message, bot: Bot):
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    ref_count = await repository.get_referral_count(message.from_user.id)
    ref_bonus = await repository.get_setting("ref_bonus") or "10000"

    text = (
        f"🔗 <b>Sizning referal havolangiz</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 Taklif qilganlar: <b>{ref_count} ta</b>\n"
        f"💰 Har bir odam uchun: <b>{ref_bonus} so'm</b>\n\n"
        f"💡 Havolani do'stlaringizga yuboring!"
    )
    await message.answer(text, parse_mode="HTML")


# ── TOP 10 ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "🏆 TOP 10")
async def btn_top(message: Message):
    top = await repository.get_top_referrers(10)
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines  = ["🏆 <b>TOP 10 referalchilar</b>\n"]

    for i, row in enumerate(top):
        if row["ref_count"] == 0:
            continue
        name = row["first_name"] or "Nomsiz"
        uname = f"@{row['username']}" if row["username"] else f"ID:{row['telegram_id']}"
        lines.append(f"{medals[i]} {name} ({uname}) — <b>{row['ref_count']} ta</b>")

    if len(lines) == 1:
        lines.append("Hali referallar yo'q.")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── TICKETLAR ──────────────────────────────────────────────────────────────────

@router.message(F.text == "🎫 Mening ticketlarim")
async def btn_my_tickets(message: Message):
    tickets = await repository.get_user_tickets(message.from_user.id)
    if not tickets:
        await message.answer("🎫 Sizda hali ticket yo'q.")
        return

    status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    lines = ["🎫 <b>Sizning ticketlaringiz</b>\n"]
    for t in tickets:
        emoji  = status_emoji.get(t["status"], "❓")
        date   = t["created_at"].strftime("%d.%m.%Y %H:%M")
        card   = t["card_number"]
        masked = f"{card[:4]} **** **** {card[-4:]}" if card and len(card) >= 8 else card
        lines.append(
            f"{emoji} <b>#{t['id']}</b> — {t['amount']:,} so'm\n"
            f"   💳 {masked} | 📅 {date}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── INFO PAGES ─────────────────────────────────────────────────────────────────

@router.message(F.text == "📌 Loyiha haqida")
async def btn_about(message: Message):
    text = await repository.get_setting("about_text") or "Loyiha haqida ma'lumot yo'q."
    await message.answer(f"📌 <b>Loyiha haqida</b>\n\n{text}", parse_mode="HTML")


@router.message(F.text == "❓ Savol-javob")
async def btn_faq(message: Message):
    text = await repository.get_setting("faq_text") or "FAQ mavjud emas."
    await message.answer(f"❓ <b>Savol-javob</b>\n\n{text}", parse_mode="HTML")


@router.message(F.text == "📍 Manzil")
async def btn_address(message: Message):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    text     = await repository.get_setting("address_text") or "Manzil ko'rsatilmagan."
    maps_url = await repository.get_setting("maps_url") or "https://maps.google.com"
    builder  = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗺 Google Maps", url=maps_url))
    await message.answer(f"📍 <b>Manzil</b>\n\n{text}", parse_mode="HTML",
                         reply_markup=builder.as_markup())


@router.message(F.text == "📞 Aloqa")
async def btn_contact(message: Message):
    support = await repository.get_setting("support_username") or "@support"
    channel = await repository.get_setting("channel_username") or ""
    text = (
        f"📞 <b>Aloqa</b>\n\n"
        f"💬 Yordam: {support}\n"
        + (f"📢 Kanal: {channel}\n" if channel else "") +
        f"\nSavol yoki takliflaringiz bo'lsa yozing!"
    )
    await message.answer(text, parse_mode="HTML")
