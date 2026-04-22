from __future__ import annotations
from typing import Optional
import asyncpg
from database.connection import get_pool


# ── USERS ──────────────────────────────────────────────────────────────────────

async def get_user(telegram_id: int) -> Optional[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)

async def get_or_create_user(telegram_id: int, first_name: str,
                              last_name: Optional[str], username: Optional[str],
                              referrer_id: Optional[int] = None) -> tuple[asyncpg.Record, bool]:
    existing = await get_user(telegram_id)
    if existing:
        await pool_execute(
            "UPDATE users SET first_name=$2, last_name=$3, username=$4 WHERE telegram_id=$1",
            telegram_id, first_name, last_name, username
        )
        return await get_user(telegram_id), False
    pool = await get_pool()
    record = await pool.fetchrow(
        "INSERT INTO users (telegram_id, first_name, last_name, username, referrer_id) "
        "VALUES ($1,$2,$3,$4,$5) RETURNING *",
        telegram_id, first_name, last_name, username, referrer_id
    )
    return record, True

async def pool_execute(query: str, *args):
    pool = await get_pool()
    return await pool.execute(query, *args)

async def add_balance(telegram_id: int, amount: int) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE users SET balance = balance + $2 WHERE telegram_id = $1 RETURNING balance",
        telegram_id, amount
    )
    return row["balance"] if row else 0

async def deduct_balance(telegram_id: int, amount: int) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE users SET balance = balance - $2 "
        "WHERE telegram_id = $1 AND balance >= $2 RETURNING balance",
        telegram_id, amount
    )
    return row is not None

async def get_total_users() -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")

async def get_all_user_ids() -> list[int]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM users WHERE is_blocked = FALSE")
    return [r["telegram_id"] for r in rows]

async def mark_blocked(telegram_id: int):
    await pool_execute("UPDATE users SET is_blocked=TRUE WHERE telegram_id=$1", telegram_id)

async def get_top_referrers(limit: int = 10) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT u.telegram_id, u.first_name, u.username, COUNT(r.id) AS ref_count "
        "FROM users u LEFT JOIN referrals r ON r.user_id = u.telegram_id "
        "GROUP BY u.telegram_id, u.first_name, u.username "
        "ORDER BY ref_count DESC LIMIT $1", limit
    )


# ── REFERRALS ──────────────────────────────────────────────────────────────────

async def create_referral(user_id: int, referred_user_id: int):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO referrals (user_id, referred_user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
        user_id, referred_user_id
    )

async def get_referral_count(user_id: int) -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM referrals WHERE user_id=$1", user_id)

async def get_referral_earnings(user_id: int) -> int:
    pool = await get_pool()
    count = await pool.fetchval("SELECT COUNT(*) FROM referrals WHERE user_id=$1", user_id)
    ref_bonus = int(await get_setting("ref_bonus") or "10000")
    return count * ref_bonus


# ── TICKETS ────────────────────────────────────────────────────────────────────

async def create_ticket(user_id: int, amount: int, card_number: str) -> asyncpg.Record:
    pool = await get_pool()
    return await pool.fetchrow(
        "INSERT INTO tickets (user_id, amount, card_number) VALUES ($1,$2,$3) RETURNING *",
        user_id, amount, card_number
    )

async def get_user_tickets(user_id: int) -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM tickets WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10", user_id
    )

async def get_pending_tickets() -> list[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT t.*, u.first_name, u.username FROM tickets t "
        "JOIN users u ON u.telegram_id = t.user_id "
        "WHERE t.status='pending' ORDER BY t.created_at ASC"
    )

async def update_ticket_status(ticket_id: int, status: str):
    await pool_execute(
        "UPDATE tickets SET status=$2, updated_at=NOW() WHERE id=$1", ticket_id, status
    )

async def get_ticket(ticket_id: int) -> Optional[asyncpg.Record]:
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM tickets WHERE id=$1", ticket_id)


# ── SETTINGS ───────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> Optional[str]:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT value FROM settings WHERE key=$1", key)
    return row["value"] if row else None

async def set_setting(key: str, value: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO settings (key,value) VALUES ($1,$2) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
        key, value
    )

async def get_all_settings() -> dict[str, str]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT key, value FROM settings ORDER BY key")
    return {r["key"]: r["value"] for r in rows}


# ── VOTES ──────────────────────────────────────────────────────────────────────

async def get_vote(user_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM votes WHERE user_id=$1", user_id)

async def create_vote(user_id: int, full_name: str, phone: str):
    pool = await get_pool()
    return await pool.fetchrow(
        "INSERT INTO votes (user_id, full_name, phone) VALUES ($1,$2,$3) "
        "ON CONFLICT (user_id) DO UPDATE SET full_name=$2, phone=$3 RETURNING *",
        user_id, full_name, phone
    )

async def get_all_votes(limit: int = 100) -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT v.*, u.username FROM votes v "
        "JOIN users u ON u.telegram_id = v.user_id "
        "ORDER BY v.created_at DESC LIMIT $1", limit
    )

async def get_votes_count() -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM votes")


# ── OTP SESSIONS ───────────────────────────────────────────────────────────────

async def save_otp_session(user_id: int, phone: str, otp_key: str):
    pool = await get_pool()
    # Delete old sessions for this user
    await pool.execute("DELETE FROM otp_sessions WHERE user_id=$1", user_id)
    await pool.execute(
        "INSERT INTO otp_sessions (user_id, phone, otp_key) VALUES ($1,$2,$3)",
        user_id, phone, otp_key
    )

async def get_otp_session(user_id: int):
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM otp_sessions WHERE user_id=$1 AND expires_at > NOW()",
        user_id
    )

async def delete_otp_session(user_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM otp_sessions WHERE user_id=$1", user_id)
