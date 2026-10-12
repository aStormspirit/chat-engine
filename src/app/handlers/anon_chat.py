import logging

from telethon import TelegramClient, events

from app.services.anon_chat import AnonChatService

logger = logging.getLogger(__name__)


def register(client: TelegramClient, *, service: AnonChatService) -> None:
    async def handle_bot_message(event: events.NewMessage.Event) -> None:
        text = event.message.message or ""
        if not text:
            return
        await service.handle_bot_message(text)

    client.add_event_handler(
        handle_bot_message,
        events.NewMessage(from_users=service.bot_username, incoming=True),
    )
