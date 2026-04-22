"""
User handlers with full OpenBudget OTP + real vote flow.
Fallback to local name+phone if API is down.
"""
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from loguru import logger

from app.keyboards import main_menu_kb, cancel_kb
from app.services.openbudget import (
    solve_and_send_otp, verify_otp, cast_vote,
    get_active_initiatives, check_api_available, OpenBudgetError,
    _normalize_phone_full
)
from database import repository
from config import settings

router = Router(name="user")


# ── FSM ────────────────────────────────────────────────────────────────────────

class VoteStates(StatesGroup):
    waiting_phone      = State()   # OTP mode
    waiting_otp        = State()   # OTP mode
    waiting_name_local = State()   # Fallback
    waiting_phone_local= State()   # Fallback

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


async def give_vote_bonus(user_id: int) -> tuple[int, int]:
    """Add vote bonus, return (bonus, new_balance)."""
    bonus = int(await repository.get_setting("vote_bonus") or "30000")
    new_bal = await repository.add_balance(user_id, bonus)
    return bonus, new_bal


async def notify_admins(bot: Bot, tg_user, phone: str, via_api: bool, voted_on_site: bool):
    votes_count = await repository.get_votes_count()
    method = "✅ OTP tasdiqlangan" if via_api else "📝 Lokal saqlash"
    site   = "✅ Saytda ovoz berildi" if voted_on_site else "—"
    for admin_id in settings.admin_ids_list:
        try:
            uname = f"@{tg_user.username}" if tg_user.username else f"ID:{tg_user.id}"
            await bot.send_message(
                admin_id,
                f"🗳 <b>Yangi ovoz!</b>\n\n"
                f"👤 {tg_user.full_name}\n"
                f"📱 +{phone}\n"
                f"🔗 {uname}\n"
                f"🔧 {method}\n"
                f"🌐 Sayt: {site}\n"
                f"📊 Jami ovozlar: <b>{votes_count}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass


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

    if is_new and referrer_id:
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 Siz orqali <b>{name}</b> qo'shildi!\n"
                f"💰 <b>{ref_bonus} so'm</b> qo'shildi!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await message.answer(f"{name} 👋 {welcome}", parse_mode="HTML",
                         reply_markup=main_menu_kb())


# ── OVOZ BERISH ────────────────────────────────────────────────────────────────

@router.message(F.text == "🗳 Ovoz berish")
async def btn_vote(message: Message, state: FSMContext):
    vote_enabled = await repository.get_setting("vote_enabled") or "true"
    if vote_enabled.lower() != "true":
        await message.answer("⏸ Ovoz berish hozircha to'xtatilgan.")
        return

    # Already voted?
    existing = await repository.get_vote(message.from_user.id)
    if existing:
        vote_bonus = await repository.get_setting("vote_bonus") or "30000"
        await message.answer(
            f"✅ <b>Siz allaqachon ovoz bergansiz!</b>\n\n"
            f"📱 +{existing['phone']}\n"
            f"💰 {int(vote_bonus):,} so'm olindingiz",
            parse_mode="HTML"
        )
        return

    wait_msg = await message.answer("⏳ Tekshirilmoqda...")
    api_ok = await check_api_available()
    vote_bonus = await repository.get_setting("vote_bonus") or "30000"

    if api_ok:
        await state.set_state(VoteStates.waiting_phone)
        await wait_msg.edit_text(
            f"🗳 <b>Ovoz berish</b>\n\n"
            f"💰 Ovoz uchun <b>{int(vote_bonus):,} so'm</b> olasiz!\n\n"
            f"📱 Telefon raqamingizni kiriting:\n"
            f"<i>Masalan: +998901234567</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
    else:
        # Fallback: local mode
        await state.set_state(VoteStates.waiting_name_local)
        await wait_msg.edit_text(
            f"🗳 <b>Ovoz berish</b>\n\n"
            f"💰 Ovoz uchun <b>{int(vote_bonus):,} so'm</b> olasiz!\n\n"
            f"📝 To'liq ismingizni kiriting:\n"
            f"<i>Masalan: Rahimjonov Asadbek</i>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )


# ── OTP FLOW ───────────────────────────────────────────────────────────────────

@router.message(VoteStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip() if message.text else ""
    clean = phone.replace("+","").replace(" ","").replace("-","")
    if not clean.isdigit() or len(clean) < 9:
        await message.answer("❌ Noto'g'ri telefon!\nMasalan: +998901234567")
        return

    full = _normalize_phone_full(clean)
    wait_msg = await message.answer("⏳ SMS yuborilmoqda, kuting (10-30 soniya)...")

    try:
        otp_key = await solve_and_send_otp(full)
    except OpenBudgetError as e:
        logger.warning(f"OTP failed ({e}), switching to local mode")
        await state.set_state(VoteStates.waiting_name_local)
        await wait_msg.edit_text(
            "⚠️ Openbudget API hozir ishlamayapti.\n\n"
            "📝 To'liq ismingizni kiriting:",
            reply_markup=cancel_kb()
        )
        return
    except Exception as e:
        logger.error(f"Unexpected OTP error: {e}")
        await wait_msg.edit_text("❌ Texnik xato. Biroz kutib qayta urinib ko'ring.")
        await state.clear()
        return

    await repository.save_otp_session(message.from_user.id, full, otp_key)
    await state.update_data(phone=full)
    await state.set_state(VoteStates.waiting_otp)

    await wait_msg.edit_text(
        f"✅ <b>SMS yuborildi!</b>\n\n"
        f"📱 +{full}\n\n"
        f"📨 <b>Openbudget</b> dan kelgan 6 xonali kodni kiriting:\n"
        f"<i>Kod 5 daqiqada eskiradi</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@router.message(VoteStates.waiting_otp)
async def process_otp(message: Message, state: FSMContext, bot: Bot):
    code = message.text.strip() if message.text else ""
    if not code.isdigit() or len(code) != 6:
        await message.answer("❌ Kod 6 ta raqamdan iborat bo'lishi kerak!")
        return

    session = await repository.get_otp_session(message.from_user.id)
    if not session:
        await message.answer(
            "❌ Sessiya muddati o'tdi! Qaytadan bosing.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    wait_msg = await message.answer("⏳ Tekshirilmoqda...")

    try:
        result = await verify_otp(session["phone"], session["otp_key"], code)
    except OpenBudgetError as e:
        await wait_msg.edit_text(f"❌ {e}\n\nQayta kodni kiriting:")
        return
    except Exception as e:
        logger.error(f"verify_otp error: {e}")
        await wait_msg.edit_text("❌ Texnik xato. Qayta urinib ko'ring.")
        return

    phone        = session["phone"]
    access_token = result.get("access_token", "")
    await repository.delete_otp_session(message.from_user.id)

    # Try to cast vote on openbudget.uz
    voted_on_site   = False
    initiative_id   = await repository.get_setting("initiative_id") or ""
    if not initiative_id and access_token:
        # Auto-detect active initiative
        initiatives = await get_active_initiatives(access_token)
        if initiatives:
            initiative_id = str(initiatives[0].get("id", ""))
            logger.info(f"Auto-detected initiative: {initiative_id}")

    if initiative_id and access_token:
        voted_on_site = await cast_vote(access_token, initiative_id)
        logger.info(f"Vote on site: {voted_on_site}")

    # Save locally
    await repository.create_vote(message.from_user.id, message.from_user.full_name, phone)
    bonus, new_bal = await give_vote_bonus(message.from_user.id)
    await state.clear()

    site_line = "\n🌐 <b>Saytda ham ovoz berildi!</b>" if voted_on_site else ""
    await wait_msg.edit_text(
        f"🎉 <b>Ovozingiz tasdiqlandi!</b>"
        f"{site_line}\n\n"
        f"📱 +{phone}\n"
        f"💰 <b>{bonus:,} so'm</b> qo'shildi!\n"
        f"💵 Balans: <b>{new_bal:,} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    await notify_admins(bot, message.from_user, phone, via_api=True, voted_on_site=voted_on_site)


# ── LOCAL FALLBACK ─────────────────────────────────────────────────────────────

@router.message(VoteStates.waiting_name_local)
async def process_local_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if len(name) < 5 or any(c.isdigit() for c in name):
        await message.answer("❌ To'liq ism-sharifingizni kiriting!")
        return
    await state.update_data(full_name=name)
    await state.set_state(VoteStates.waiting_phone_local)
    await message.answer(
        f"✅ Ism: <b>{name}</b>\n\n📱 Telefon raqamingizni kiriting:",
        parse_mode="HTML", reply_markup=cancel_kb()
    )


@router.message(VoteStates.waiting_phone_local)
async def process_local_phone(message: Message, state: FSMContext, bot: Bot):
    phone = message.text.strip() if message.text else ""
    clean = phone.replace("+","").replace(" ","").replace("-","")
    if not clean.isdigit() or len(clean) < 9:
        await message.answer("❌ Noto'g'ri telefon!")
        return
    full = _normalize_phone_full(clean)
    data = await state.get_data()
    full_name = data.get("full_name", message.from_user.full_name)

    await repository.create_vote(message.from_user.id, full_name, full)
    bonus, new_bal = await give_vote_bonus(message.from_user.id)
    await state.clear()

    await message.answer(
        f"🎉 <b>Ma'lumotlaringiz saqlandi!</b>\n\n"
        f"👤 {full_name}\n📱 +{full}\n"
        f"💰 <b>{bonus:,} so'm</b> qo'shildi!\n"
        f"💵 Balans: <b>{new_bal:,} so'm</b>",
        parse_mode="HTML", reply_markup=main_menu_kb()
    )
    await notify_admins(bot, message.from_user, full, via_api=False, voted_on_site=False)


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
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    ref_count = await repository.get_referral_count(message.from_user.id)
    min_w     = await repository.get_setting("min_withdraw") or "50000"
    voted     = await repository.get_vote(message.from_user.id)
    v_status  = "✅ Ovoz bergan" if voted else "❌ Hali ovoz bermagan"
    await message.answer(
        f"💰 <b>Balans</b>\n\n"
        f"👤 {user['first_name']}\n"
        f"💵 Balans: <b>{user['balance']:,} so'm</b>\n"
        f"👥 Referallar: <b>{ref_count} ta</b>\n"
        f"🗳 {v_status}\n\n"
        f"🔗 Havolangiz:\n<code>{ref_link}</code>\n\n"
        f"💡 Minimal yechish: {int(min_w):,} so'm",
        parse_mode="HTML"
    )


# ── PULNI YECHIB OLISH ─────────────────────────────────────────────────────────

@router.message(F.text == "💳 Pulni yechib olish")
async def btn_withdraw(message: Message, state: FSMContext):
    if (await repository.get_setting("withdraw_enabled") or "true").lower() != "true":
        await message.answer("⏸ Yechib olish to'xtatilgan.")
        return
    user  = await repository.get_user(message.from_user.id)
    min_w = int(await repository.get_setting("min_withdraw") or "50000")
    if not user:
        await message.answer("Avval /start bosing.")
        return
    if user["balance"] < min_w:
        await message.answer(
            f"❌ Balans yetarli emas!\n"
            f"💵 {user['balance']:,} so'm\n📌 Minimal: {min_w:,} so'm",
            parse_mode="HTML"
        )
        return
    await state.set_state(WithdrawStates.waiting_amount)
    await message.answer(
        f"💳 <b>Pul yechish</b>\n\n"
        f"💵 Balans: <b>{user['balance']:,} so'm</b>\n\nQancha yechmoqchisiz?",
        parse_mode="HTML", reply_markup=cancel_kb()
    )


@router.message(WithdrawStates.waiting_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.replace(" ","").replace(",",""))
    except (ValueError, AttributeError):
        await message.answer("❌ Faqat raqam!")
        return
    user  = await repository.get_user(message.from_user.id)
    min_w = int(await repository.get_setting("min_withdraw") or "50000")
    if amount < min_w:
        await message.answer(f"❌ Minimal {min_w:,} so'm!")
        return
    if amount > user["balance"]:
        await message.answer("❌ Balansingizdan ko'p!")
        return
    await state.update_data(amount=amount)
    await state.set_state(WithdrawStates.waiting_card)
    await message.answer("💳 Karta raqamingizni kiriting (16 raqam):", reply_markup=cancel_kb())


@router.message(WithdrawStates.waiting_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    card = message.text.replace(" ","") if message.text else ""
    if not card.isdigit() or len(card) < 16:
        await message.answer("❌ 16 ta raqam kiriting!")
        return
    data   = await state.get_data()
    amount = data["amount"]
    if not await repository.deduct_balance(message.from_user.id, amount):
        await state.clear()
        await message.answer("❌ Balans yetarli emas!")
        return
    ticket = await repository.create_ticket(message.from_user.id, amount, card)
    await state.clear()
    await message.answer(
        f"✅ <b>So'rov yuborildi!</b>\n\n"
        f"🎫 #{ticket['id']} | 💵 {amount:,} so'm\n"
        f"💳 {card[:4]} **** **** {card[-4:]}\n⏳ 24 soat ichida",
        parse_mode="HTML", reply_markup=main_menu_kb()
    )


# ── INFO BUTTONS ───────────────────────────────────────────────────────────────

@router.message(F.text == "🔗 Referal ssilka")
async def btn_referral(message: Message, bot: Bot):
    bot_info  = await bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    ref_count = await repository.get_referral_count(message.from_user.id)
    ref_bonus = await repository.get_setting("ref_bonus") or "10000"
    await message.answer(
        f"🔗 <b>Referal havolangiz</b>\n\n<code>{ref_link}</code>\n\n"
        f"👥 Taklif qilganlar: <b>{ref_count} ta</b>\n"
        f"💰 Har bir odam: <b>{int(ref_bonus):,} so'm</b>",
        parse_mode="HTML"
    )


@router.message(F.text == "🏆 TOP 10")
async def btn_top(message: Message):
    top    = await repository.get_top_referrers(10)
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    lines  = ["🏆 <b>TOP 10 referalchilar</b>\n"]
    for i, row in enumerate(top):
        if row["ref_count"] == 0: continue
        name  = row["first_name"] or "Nomsiz"
        uname = f"@{row['username']}" if row["username"] else f"ID:{row['telegram_id']}"
        lines.append(f"{medals[i]} {name} ({uname}) — <b>{row['ref_count']} ta</b>")
    if len(lines) == 1:
        lines.append("Hali referallar yo'q.")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "🎫 Mening ticketlarim")
async def btn_my_tickets(message: Message):
    tickets = await repository.get_user_tickets(message.from_user.id)
    if not tickets:
        await message.answer("🎫 Hali ticket yo'q.")
        return
    status_emoji = {"pending":"⏳","approved":"✅","rejected":"❌"}
    lines = ["🎫 <b>Ticketlaringiz</b>\n"]
    for t in tickets:
        e    = status_emoji.get(t["status"],"❓")
        date = t["created_at"].strftime("%d.%m %H:%M")
        c    = t["card_number"] or ""
        m    = f"{c[:4]}****{c[-4:]}" if len(c)>=8 else c
        lines.append(f"{e} #{t['id']} — {t['amount']:,} so'm | {m} | {date}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "📌 Loyiha haqida")
async def btn_about(message: Message):
    text = await repository.get_setting("about_text") or "Ma'lumot yo'q."
    await message.answer(f"📌 <b>Loyiha haqida</b>\n\n{text}", parse_mode="HTML")


@router.message(F.text == "❓ Savol-javob")
async def btn_faq(message: Message):
    text = await repository.get_setting("faq_text") or "FAQ yo'q."
    await message.answer(f"❓ <b>Savol-javob</b>\n\n{text}", parse_mode="HTML")


@router.message(F.text == "📍 Manzil")
async def btn_address(message: Message):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    text     = await repository.get_setting("address_text") or "Manzil ko'rsatilmagan."
    maps_url = await repository.get_setting("maps_url") or "https://maps.google.com"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🗺 Google Maps", url=maps_url))
    await message.answer(f"📍 <b>Manzil</b>\n\n{text}", parse_mode="HTML",
                         reply_markup=b.as_markup())


@router.message(F.text == "📞 Aloqa")
async def btn_contact(message: Message):
    support = await repository.get_setting("support_username") or "@support"
    channel = await repository.get_setting("channel_username") or ""
    text = f"📞 <b>Aloqa</b>\n\n💬 {support}" + (f"\n📢 {channel}" if channel else "")
    await message.answer(text, parse_mode="HTML")
