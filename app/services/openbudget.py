"""
OpenBudget.uz full API integration.
Flow: captcha → solve → send-otp → verify-otp → cast vote
"""
import asyncio
import aiohttp
from loguru import logger

BASE_URL       = "https://openbudget.uz/api"
CAPTCHA_URL    = f"{BASE_URL}/v2/vote/captcha-2"
SEND_OTP_URL   = f"{BASE_URL}/v1/login/send-otp"
VERIFY_OTP_URL = f"{BASE_URL}/v1/login/verify-otp"
ACTIVE_URL     = f"{BASE_URL}/v1/initiatives/active"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://openbudget.uz",
    "Referer": "https://openbudget.uz/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en-US;q=0.9,en;q=0.8,uz;q=0.7",
}

TWOCAPTCHA_KEY = "47838d0c21608ceac94400b17bd6b84d"


class OpenBudgetError(Exception):
    pass


# ── STEP 1: GET CAPTCHA ────────────────────────────────────────────────────────

async def get_captcha() -> dict:
    """GET /api/v2/vote/captcha-2 → {captchaKey, image}"""
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(CAPTCHA_URL, timeout=timeout) as r:
            if r.status != 200:
                raise OpenBudgetError(f"Captcha xato: {r.status}")
            data = await r.json(content_type=None)
            return {
                "key":   data["captchaKey"],
                "image": data["image"],  # base64 JPEG
            }


# ── STEP 2: SOLVE CAPTCHA VIA 2CAPTCHA ────────────────────────────────────────

async def solve_captcha(image_b64: str) -> int:
    """Send image to 2captcha, get math result as int."""
    # Strip data URI prefix if any
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession() as s:
        # Submit task
        form = {
            "key":     TWOCAPTCHA_KEY,
            "method":  "base64",
            "body":    image_b64,
            "numeric": "1",
            "calc":    "1",
            "min_len": "1",
            "max_len": "3",
            "json":    "1",
        }
        async with s.post("https://2captcha.com/in.php", data=form, timeout=timeout) as r:
            res = await r.json(content_type=None)
            if res.get("status") != 1:
                raise OpenBudgetError(f"2captcha submit xato: {res}")
            task_id = res["request"]
            logger.debug(f"2captcha task: {task_id}")

        # Poll result
        poll_url = (
            f"https://2captcha.com/res.php"
            f"?key={TWOCAPTCHA_KEY}&action=get&id={task_id}&json=1"
        )
        for attempt in range(20):
            await asyncio.sleep(3)
            async with s.get(poll_url, timeout=timeout) as r:
                res = await r.json(content_type=None)
                if res.get("status") == 1:
                    answer = int(res["request"])
                    logger.debug(f"2captcha solved: {answer}")
                    return answer
                if "ERROR" in str(res.get("request", "")):
                    raise OpenBudgetError(f"2captcha error: {res['request']}")
                logger.debug(f"2captcha waiting... attempt {attempt+1}")

    raise OpenBudgetError("2captcha timeout (60s)")


# ── STEP 3: SEND OTP ───────────────────────────────────────────────────────────

async def send_otp(phone: str, captcha_key: str, captcha_result: int) -> str:
    """
    POST /api/v1/login/send-otp
    Body: {captcha_key, captcha_result, phone_number}
    Returns: otpKey
    """
    phone = _normalize_phone_full(phone)  # 998901234567
    payload = {
        "captcha_key":    captcha_key,
        "captcha_result": captcha_result,
        "phone_number":   phone,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.post(SEND_OTP_URL, json=payload, timeout=timeout) as r:
            data = await r.json(content_type=None)
            logger.debug(f"send-otp [{r.status}]: {data}")
            if r.status == 400:
                msg = data.get("message") or data.get("error") or str(data)
                raise OpenBudgetError(f"SMS xato: {msg}")
            if r.status != 200:
                raise OpenBudgetError(f"SMS yuborishda xato: {r.status}")
            otp_key = data.get("otpKey")
            if not otp_key:
                raise OpenBudgetError("otpKey kelmadi")
            retry_after = data.get("retryAfter", 60)
            logger.info(f"OTP sent to {phone}, retryAfter={retry_after}s")
            return otp_key


# ── STEP 4: VERIFY OTP ─────────────────────────────────────────────────────────

async def verify_otp(phone: str, otp_key: str, otp_code: str) -> dict:
    """
    POST /api/v1/login/verify-otp
    Body: {otp_code, otp_key, phone_number (9-digit)}
    Returns: {access_token, refresh_token, exists, role}
    """
    phone_short = _normalize_phone_short(phone)  # 900271188
    payload = {
        "otp_code":     otp_code,
        "otp_key":      otp_key,
        "phone_number": phone_short,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.post(VERIFY_OTP_URL, json=payload, timeout=timeout) as r:
            data = await r.json(content_type=None)
            logger.debug(f"verify-otp [{r.status}]")
            if r.status == 400:
                raise OpenBudgetError("Kod noto'g'ri yoki muddati o'tgan!")
            if r.status != 200:
                raise OpenBudgetError(f"Tasdiqlashda xato: {r.status}")
            return data  # {access_token, refresh_token, exists, role, ...}


# ── STEP 5: CAST VOTE ──────────────────────────────────────────────────────────

async def get_active_initiatives(access_token: str) -> list:
    """GET /api/v1/initiatives/active - get available initiatives to vote."""
    h = {**HEADERS, "Authorization": f"Bearer {access_token}"}
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(headers=h) as s:
            async with s.get(ACTIVE_URL, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception as e:
        logger.error(f"get_active_initiatives error: {e}")
    return []


async def cast_vote(access_token: str, initiative_id: str) -> bool:
    """POST /api/v1/initiatives/{id}/vote - cast actual vote."""
    url = f"{BASE_URL}/v1/initiatives/{initiative_id}/vote"
    h   = {**HEADERS, "Authorization": f"Bearer {access_token}"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(headers=h) as s:
            async with s.post(url, timeout=timeout) as r:
                data = await r.json(content_type=None)
                logger.info(f"cast_vote [{r.status}]: {data}")
                return r.status in (200, 201)
    except Exception as e:
        logger.error(f"cast_vote error: {e}")
        return False


# ── FULL FLOW ──────────────────────────────────────────────────────────────────

async def check_api_available() -> bool:
    """Quick check if openbudget API is up."""
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession() as s:
            async with s.get(CAPTCHA_URL, headers=HEADERS, timeout=timeout) as r:
                return r.status == 200
    except Exception:
        return False


async def solve_and_send_otp(phone: str) -> str:
    """
    Full captcha→solve→send flow.
    Returns otpKey for the verify step.
    """
    logger.info(f"Starting OTP flow for {_normalize_phone_full(phone)}")
    captcha = await get_captcha()
    answer  = await solve_captcha(captcha["image"])
    otp_key = await send_otp(phone, captcha["key"], answer)
    return otp_key


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _normalize_phone_full(phone: str) -> str:
    """Clean phone to 12-digit: 998901234567"""
    p = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not p.startswith("998"):
        p = "998" + p
    return p


def _normalize_phone_short(phone: str) -> str:
    """Clean phone to 9-digit: 901234567"""
    p = _normalize_phone_full(phone)
    return p[3:] if p.startswith("998") and len(p) == 12 else p
