import logging
import time

from telethon import TelegramClient, events

logger = logging.getLogger(__name__)


async def handle_ping(event: events.NewMessage.Event) -> None:
    started = time.perf_counter()
    message = await event.respond("pong")
    elapsed_ms = (time.perf_counter() - started) * 1000

    logger.info("Ping (%.1f ms)", elapsed_ms)
    await message.edit(f"pong — {elapsed_ms:.0f} ms")


def register(client: TelegramClient) -> None:
    # Saved Messages only, so the command can never leak into a live dialog.
    client.add_event_handler(
        handle_ping,
        events.NewMessage(pattern=r"^[/.]ping$", outgoing=True, chats="me"),
    )
