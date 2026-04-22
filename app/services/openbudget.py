"""
OpenBudget.uz API integration with fallback to local vote storage.
"""
import asyncio
import aiohttp
from loguru import logger

CAPTCHA_URL    = "https://openbudget.uz/api/v2/vote/captcha-2"
SEND_OTP_URL   = "https://openbudget.uz/api/v1/login/send-otp"
VERIFY_OTP_URL = "https://openbudget.uz/api/v1/login/verify-otp"
VOTE_URL       = "https://openbudget.uz/api/v1/initiatives/{initiative_id}/vote"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://openbudget.uz",
    "Referer": "https://openbudget.uz/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


class OpenBudgetError(Exception):
    pass


async def check_api_available() -> bool:
    """Check if openbudget.uz API is available."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                CAPTCHA_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


async def get_captcha() -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            CAPTCHA_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                raise OpenBudgetError(f"Captcha olishda xato: {resp.status}")
            data = await resp.json()
            return {"key": data["captchaKey"], "image_b64": data["image"]}


async def solve_captcha_2captcha(api_key: str, image_b64: str) -> str:
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    async with aiohttp.ClientSession() as session:
        submit_data = {
            "key": api_key, "method": "base64", "body": image_b64,
            "json": 1, "numeric": 1, "calc": 1, "min_len": 1, "max_len": 3,
        }
        async with session.post("https://2captcha.com/in.php", data=submit_data) as resp:
            result = await resp.json()
            if result.get("status") != 1:
                raise OpenBudgetError(f"2captcha xato: {result}")
            task_id = result["request"]

        result_url = f"https://2captcha.com/res.php?key={api_key}&action=get&id={task_id}&json=1"
        for _ in range(15):
            await asyncio.sleep(2)
            async with session.get(result_url) as resp:
                res = await resp.json()
                if res.get("status") == 1:
                    return res["request"]
                if res.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                    raise OpenBudgetError("Captcha hal qilib bolmadi")
    raise OpenBudgetError("2captcha timeout")


async def send_otp(phone: str, captcha_key: str, captcha_result: str) -> str:
    phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    payload = {
        "captcha_key": captcha_key,
        "captcha_result": int(captcha_result),
        "phone_number": phone,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(SEND_OTP_URL, json=payload, headers=HEADERS) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise OpenBudgetError(f"SMS yuborishda xato: {data}")
            otp_key = data.get("otpKey")
            if not otp_key:
                raise OpenBudgetError("otpKey kelmadi")
            return otp_key


async def verify_otp(phone: str, otp_key: str, otp_code: str) -> dict:
    phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    phone_short = phone[3:] if phone.startswith("998") and len(phone) == 12 else phone
    payload = {"otp_code": otp_code, "otp_key": otp_key, "phone_number": phone_short}
    async with aiohttp.ClientSession() as session:
        async with session.post(VERIFY_OTP_URL, json=payload, headers=HEADERS) as resp:
            data = await resp.json()
            if resp.status == 400:
                raise OpenBudgetError("Kod notogri yoki muddati otgan!")
            if resp.status != 200:
                raise OpenBudgetError(f"Tasdiqlashda xato: {resp.status}")
            return data


async def cast_vote(access_token: str, initiative_id: str) -> bool:
    """Cast vote on openbudget.uz after successful OTP verification."""
    url = VOTE_URL.format(initiative_id=initiative_id)
    headers = {**HEADERS, "Authorization": f"Bearer {access_token}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                logger.info(f"Vote cast status: {resp.status}")
                return resp.status in (200, 201)
    except Exception as e:
        logger.error(f"Vote cast error: {e}")
        return False


async def solve_and_send_otp(phone: str, captcha_api_key: str) -> str:
    captcha = await get_captcha()
    answer  = await solve_captcha_2captcha(captcha_api_key, captcha["image_b64"])
    otp_key = await send_otp(phone, captcha["key"], answer)
    logger.info(f"OTP sent to {phone}")
    return otp_key
