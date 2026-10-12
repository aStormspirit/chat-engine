from telethon import TelegramClient

from app.handlers import anon_chat, echo, ping
from app.services.anon_chat import AnonChatService

__all__ = ["register_handlers"]


def register_handlers(client: TelegramClient, *, service: AnonChatService) -> None:
    ping.register(client)
    echo.register(client)
    anon_chat.register(client, service=service)
