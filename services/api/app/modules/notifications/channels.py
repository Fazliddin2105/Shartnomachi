"""Delivery channels. Each channel raises on failure so the caller can retry/fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IntegrationUnavailable
from app.integrations import telegram
from app.integrations.sms import get_sms_sender
from app.modules.notifications.models import Notification
from app.modules.users.models import User

DEFAULT_CHANNELS = ("in_app", "sms")


@dataclass(slots=True)
class Message:
    type: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def short_text(self) -> str:
        return f"LexLab: {self.title}. {self.body}"[:480]


def user_channels(user: User) -> list[str]:
    channels = (user.preferences or {}).get("channels") or list(DEFAULT_CHANNELS)
    return list(dict.fromkeys(channels))


async def send(db: AsyncSession, user: User, channel: str, msg: Message) -> None:
    match channel:
        case "in_app":
            db.add(Notification(user_id=user.id, type=msg.type, title=msg.title, body=msg.body, payload=msg.payload))
            await db.flush()
        case "sms":
            if not user.phone:
                raise IntegrationUnavailable("User has no phone number")
            await get_sms_sender().send(user.phone, msg.short_text)
        case "telegram":
            if not user.telegram_chat_id:
                raise IntegrationUnavailable("Telegram is not linked")
            await telegram.send_message(user.telegram_chat_id, msg.short_text)
        case "push" | "email":
            # FCM/APNs and SMTP adapters are wired in phase 4 (see README roadmap).
            raise IntegrationUnavailable(f"Channel '{channel}' is not configured")
        case _:
            raise IntegrationUnavailable(f"Unknown channel '{channel}'")


async def notify(db: AsyncSession, user: User, msg: Message, channels: list[str] | None = None) -> list[str]:
    """Best-effort fan-out; always falls back to in-app. Returns delivered channels."""
    delivered: list[str] = []
    for ch in channels or user_channels(user):
        try:
            await send(db, user, ch, msg)
            delivered.append(ch)
        except IntegrationUnavailable:
            continue
    if "in_app" not in delivered:
        await send(db, user, "in_app", msg)
        delivered.append("in_app")
    return delivered
