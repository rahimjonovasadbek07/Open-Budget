"""
User handlers with full OpenBudget OTP verification flow.
"""
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from loguru import logger

from app.keyboards import main_menu_kb, cancel_kb
from app.services.openbudget import solve_and_send_otp, verify_otp, OpenBudgetError
from database import repository
from config import settings

router = Router(name="user")

CAPTCHA_API_KEY = "47838d0c21608ceac94400b17bd6b84d"


class VoteStates(StatesGroup):
    waiting_phone = State()
    waiting_otp   = State()

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
        tg_user.id, tg_user.first_name or "",
        tg_user.last_name, tg_user.username, valid_ref
    )
    if is_new and valid_ref:
        await repository.create_referral(valid_ref, tg_user.id)
        ref_bonus = int(await repository.get_setting("ref_bonus") or "10000")
        await repository.add_balance(valid_ref, ref_bonus)
    return record, is_new


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
async def btn_vote(message: Message, state: FSMContext):
    vote_enabled = await repository.get_setting("vote_enabled") or "true"
    if vote_enabled.lower() != "true":
        await message.answer("⏸ Ovoz berish hozircha to'xtatilgan.")
        return

    # Already voted check
    existing = await repository.get_vote(message.from_user.id)
    if existing:
        vote_bonus = await repository.get_setting("vote_bonus") or "30000"
        await message.answer(
            f"✅ <b>Siz allaqachon ovoz bergansiz!</b>\n\n"
            f"📱 Telefon: {existing['phone']}\n"
            f"💰 Bonus: {int(vote_bonus):,} so'm olindingiz",
            parse_mode="HTML"
        )
        return

    await state.set_state(VoteStates.waiting_phone)
    vote_bonus = await repository.get_setting("vote_bonus") or "30000"
    await message.answer(
        f"🗳 <b>Ovoz berish</b>\n\n"
        f"💰 Ovoz berganingiz uchun <b>{int(vote_bonus):,} so'm</b> olasiz!\n\n"
        f"📱 Telefon raqamingizni kiriting:\n"
        f"<i>Masalan: +998901234567</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(VoteStates.waiting_phone)
async def process_vote_phone(message: Message, state: FSMContext):
    phone = message.text.strip() if message.text else ""
    clean = phone.replace("+", "").replace(" ", "").replace("-", "")

    if not clean.isdigit() or len(clean) < 9:
        await message.answer(
            "❌ Noto'g'ri telefon raqam!\n"
            "Masalan: +998901234567"
        )
        return

    # Normalize to full format
    if not clean.startswith("998"):
        clean = "998" + clean

    wait_msg = await message.answer("⏳ SMS yuborilmoqda, kuting...")

    try:
        otp_key = await solve_and_send_otp(clean, CAPTCHA_API_KEY)
    except OpenBudgetError as e:
        await wait_msg.edit_text(
            f"❌ Xato: {e}\n\n"
            f"Qayta urinib ko'ring yoki yordam so'rang."
        )
        await state.clear()
        return
    except Exception as e:
        logger.error(f"OTP send error: {e}")
        await wait_msg.edit_text("❌ Texnik xato. Biroz kutib qayta urinib ko'ring.")
        await state.clear()
        return

    # Save OTP session to DB
    await repository.save_otp_session(message.from_user.id, clean, otp_key)
    await state.update_data(phone=clean)
    await state.set_state(VoteStates.waiting_otp)

    await wait_msg.edit_text(
        f"✅ <b>SMS yuborildi!</b>\n\n"
        f"📱 Raqam: <b>+{clean}</b>\n\n"
        f"📨 Openbudget dan kelgan <b>6 xonali kodni</b> kiriting:\n"
        f"<i>(Kod 5 daqiqa ichida eskiradi)</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(VoteStates.waiting_otp)
async def process_vote_otp(message: Message, state: FSMContext, bot: Bot):
    otp_code = message.text.strip() if message.text else ""

    if not otp_code.isdigit() or len(otp_code) != 6:
        await message.answer("❌ Kod 6 ta raqamdan iborat bo'lishi kerak!")
        return

    # Get OTP session
    session = await repository.get_otp_session(message.from_user.id)
    if not session:
        await message.answer(
            "❌ Sessiya muddati o'tdi! Qaytadan telefon raqam kiriting.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    wait_msg = await message.answer("⏳ Tekshirilmoqda...")

    try:
        result = await verify_otp(session["phone"], session["otp_key"], otp_code)
    except OpenBudgetError as e:
        await wait_msg.edit_text(
            f"❌ {e}\n\n"
            f"Kodni to'g'ri kiriting yoki qaytadan SMS oling."
        )
        return
    except Exception as e:
        logger.error(f"OTP verify error: {e}")
        await wait_msg.edit_text("❌ Texnik xato. Qayta urinib ko'ring.")
        return

    # Success — save vote and give bonus
    phone = session["phone"]
    await repository.delete_otp_session(message.from_user.id)
    await repository.create_vote(message.from_user.id, message.from_user.full_name, phone)

    vote_bonus  = int(await repository.get_setting("vote_bonus") or "30000")
    new_balance = await repository.add_balance(message.from_user.id, vote_bonus)

    await state.clear()

    await wait_msg.edit_text(
        f"🎉 <b>Ovozingiz tasdiqlandi!</b>\n\n"
        f"📱 Telefon: <b>+{phone}</b>\n"
        f"💰 Hisobingizga <b>{vote_bonus:,} so'm</b> qo'shildi!\n"
        f"💵 Joriy balans: <b>{new_balance:,} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

    # Notify admins
    votes_count = await repository.get_votes_count()
    for admin_id in settings.admin_ids_list:
        try:
            uname = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
            await bot.send_message(
                admin_id,
                f"🗳 <b>Yangi tasdiqlangan ovoz!</b>\n\n"
                f"👤 {message.from_user.full_name}\n"
                f"📱 +{phone}\n"
                f"🔗 {uname}\n"
                f"📊 Jami ovozlar: <b>{votes_count}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()


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
    min_w     = await repository.get_setting("min_withdraw") or "50000"
    voted     = await repository.get_vote(message.from_user.id)
    vote_status = "✅ Ovoz bergan" if voted else "❌ Hali ovoz bermagan"

    text = (
        f"💰 <b>Balans ma'lumotlari</b>\n\n"
        f"👤 {user['first_name']}\n"
        f"💵 Balans: <b>{user['balance']:,} so'm</b>\n"
        f"👥 Referallar: <b>{ref_count} ta</b>\n"
        f"🗳 Ovoz: {vote_status}\n\n"
        f"🔗 Havolangiz:\n<code>{ref_link}</code>\n\n"
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

    user  = await repository.get_user(message.from_user.id)
    min_w = int(await repository.get_setting("min_withdraw") or "50000")

    if not user:
        await message.answer("Avval /start bosing.")
        return
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
        f"Qancha yechib olmoqchisiz?",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(WithdrawStates.waiting_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.replace(" ", "").replace(",", ""))
    except (ValueError, AttributeError):
        await message.answer("❌ Faqat raqam kiriting!")
        return

    user  = await repository.get_user(message.from_user.id)
    min_w = int(await repository.get_setting("min_withdraw") or "50000")

    if amount < min_w:
        await message.answer(f"❌ Minimal {min_w:,} so'm!")
        return
    if amount > user["balance"]:
        await message.answer(f"❌ Balansingizdan ko'p!")
        return

    await state.update_data(amount=amount)
    await state.set_state(WithdrawStates.waiting_card)
    await message.answer(
        "💳 Karta raqamingizni kiriting:\n<i>16 ta raqam</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(WithdrawStates.waiting_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    card = message.text.replace(" ", "") if message.text else ""
    if not card.isdigit() or len(card) < 16:
        await message.answer("❌ Noto'g'ri karta raqami! 16 ta raqam kiriting.")
        return

    data    = await state.get_data()
    amount  = data["amount"]
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
        f"💵 {amount:,} so'm\n"
        f"💳 {card[:4]} **** **** {card[-4:]}\n\n"
        f"⏳ 24 soat ichida to'lanadi",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


# ── REFERAL ────────────────────────────────────────────────────────────────────

@router.message(F.text == "🔗 Referal ssilka")
async def btn_referral(message: Message, bot: Bot):
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    ref_count = await repository.get_referral_count(message.from_user.id)
    ref_bonus = await repository.get_setting("ref_bonus") or "10000"
    await message.answer(
        f"🔗 <b>Sizning referal havolangiz</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 Taklif qilganlar: <b>{ref_count} ta</b>\n"
        f"💰 Har bir odam: <b>{int(ref_bonus):,} so'm</b>",
        parse_mode="HTML"
    )


# ── TOP 10 ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "🏆 TOP 10")
async def btn_top(message: Message):
    top    = await repository.get_top_referrers(10)
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    lines  = ["🏆 <b>TOP 10 referalchilar</b>\n"]
    for i, row in enumerate(top):
        if row["ref_count"] == 0:
            continue
        name  = row["first_name"] or "Nomsiz"
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
        card   = t["card_number"] or ""
        masked = f"{card[:4]} **** **** {card[-4:]}" if len(card) >= 8 else card
        lines.append(f"{emoji} <b>#{t['id']}</b> — {t['amount']:,} so'm | {masked} | {date}")
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
    from aiogram.types import InlineKeyboardButton
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
        f"📞 <b>Aloqa</b>\n\n💬 Yordam: {support}\n"
        + (f"📢 Kanal: {channel}\n" if channel else "")
    )
    await message.answer(text, parse_mode="HTML")
