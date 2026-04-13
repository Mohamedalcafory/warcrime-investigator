"""Search Telegram channels for messages matching a target string."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from investigation_agent.config import telegram_api_hash, telegram_api_id, telegram_phone

logger = logging.getLogger(__name__)


@dataclass
class TelegramHit:
    channel_username: str
    message_id: int
    text: str
    url: str
    date_iso: str


async def search_channels_for_target(
    *,
    channels: list[str],
    search_query: str,
    limit_per_channel: int = 50,
) -> list[TelegramHit]:
    """
    Search each channel for messages matching `search_query` (Telethon server-side search).
    """
    api_id = telegram_api_id()
    api_hash = telegram_api_hash()
    phone = telegram_phone()
    if not api_id or not api_hash or not phone:
        raise RuntimeError(
            "Telegram is not configured. Set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env"
        )
    if not channels:
        raise RuntimeError("No channels configured. Set TELEGRAM_CHANNELS in .env")

    hits: list[TelegramHit] = []
    client = TelegramClient("investigation_agent_session", api_id, api_hash)

    async with client:
        await client.start(phone=phone)
        for username in channels:
            try:
                entity = await client.get_entity(username)
            except Exception as e:
                logger.warning("Cannot access channel @%s: %s", username, e)
                continue
            count = 0
            try:
                async for message in client.iter_messages(
                    entity, search=search_query, limit=limit_per_channel
                ):
                    if not message or not message.id:
                        continue
                    text = message.message or ""
                    url = f"https://t.me/{username}/{message.id}"
                    dt = message.date
                    date_iso = dt.isoformat() if dt else ""
                    hits.append(
                        TelegramHit(
                            channel_username=username,
                            message_id=message.id,
                            text=text,
                            url=url,
                            date_iso=date_iso,
                        )
                    )
                    count += 1
            except FloodWaitError as e:
                logger.warning("FloodWait on @%s: %s seconds", username, e.seconds)

    return hits
