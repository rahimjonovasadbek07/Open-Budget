import asyncpg
from loguru import logger

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    first_name  VARCHAR(255) NOT NULL DEFAULT '',
    last_name   VARCHAR(255),
    username    VARCHAR(255),
    referrer_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
    balance     BIGINT NOT NULL DEFAULT 0,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_blocked  BOOLEAN NOT NULL DEFAULT FALSE
);
"""

CREATE_REFERRALS = """
CREATE TABLE IF NOT EXISTS referrals (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    referred_user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    bonus_paid       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(referred_user_id)
);
"""

CREATE_TICKETS = """
CREATE TABLE IF NOT EXISTS tickets (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    amount      BIGINT NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',
    card_number VARCHAR(50),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_VOTES = """
CREATE TABLE IF NOT EXISTS votes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    full_name   VARCHAR(255) NOT NULL,
    phone       VARCHAR(20) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);
"""

CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key        VARCHAR(100) PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_users_referrer  ON users(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_user  ON referrals(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user    ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status  ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_votes_user      ON votes(user_id);
"""

DEFAULT_SETTINGS = [
    ("bot_name",         "Open Budget Uzbekistan"),
    ("welcome_text",     "Botga xush kelibsiz!\n\n🎁 Har bir ovozga <b>{vote_bonus} so'm</b> oling va <b>iPhone 17</b> yutib olish imkoniyatiga ega bo'ling!\n\n🔗 Odam chaqirganiz uchun <b>{ref_bonus} so'm</b> beriladi"),
    ("vote_bonus",       "30000"),
    ("ref_bonus",        "10000"),
    ("min_withdraw",     "50000"),
    ("channel_username", "@openbudgettolovlari"),
    ("support_username", "@support"),
    ("maps_url",         "https://maps.google.com/?q=41.299497,69.240073"),
    ("address_text",     "Toshkent shahar, Amir Temur ko'chasi, 108-uy"),
    ("about_text",       "Bu loyiha fuqarolarning davlat byudjeti qarorlarida ishtirok etishini taminlaydi.\n\nSayt: https://openbudget.uz"),
    ("faq_text",         "<b>1. Qanday pul olaman?</b>\nOvoz berib, referal orqali do'stlarni chaqiring.\n\n<b>2. Pulni qanday yechib olaman?</b>\nBalansingiz minimum miqdorga yetgach, tugmani bosing.\n\n<b>3. Qachon to'lanadi?</b>\nAdmin tasdiqlashidan so'ng 24 soat ichida."),
    ("withdraw_enabled", "true"),
    ("vote_enabled",     "true"),
]


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            logger.info("📦 Running migrations...")
            await conn.execute(CREATE_USERS)
            await conn.execute(CREATE_REFERRALS)
            await conn.execute(CREATE_TICKETS)
            await conn.execute(CREATE_VOTES)
            await conn.execute(CREATE_SETTINGS)
            await conn.execute(CREATE_INDEXES)
            for key, value in DEFAULT_SETTINGS:
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    key, value
                )
            logger.info("✅ Migrations done")
