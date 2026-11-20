from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable


async def send_message(chat_id: str, text: str) -> None:
    token = get_settings().telegram_bot_token
    if not token:
        raise IntegrationUnavailable("Telegram bot is not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        if r.is_error:
            raise IntegrationUnavailable(f"Telegram error {r.status_code}")
