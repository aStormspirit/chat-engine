import logging

from telethon import TelegramClient, events

logger = logging.getLogger(__name__)


async def handle_echo(event: events.NewMessage.Event) -> None:
    text = event.pattern_match.group(1).strip()
    if not text:
        await event.respond("Usage: .echo <text>")
        return

    logger.info("Echo: %s", text)
    await event.respond(text)


def register(client: TelegramClient) -> None:
    # Saved Messages only, so the command can never leak into a live dialog.
    client.add_event_handler(
        handle_echo,
        events.NewMessage(pattern=r"^[/.]echo(.*)$", outgoing=True, chats="me"),
    )
