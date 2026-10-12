from pathlib import Path

from telethon import TelegramClient

from app.config import ResolvedAccount


def create_client(account: ResolvedAccount) -> TelegramClient:
    session_path = Path(account.session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    return TelegramClient(
        str(session_path),
        account.api_id,
        account.api_hash,
        app_version="4.15.2",
        device_model="PC",
        system_version="Windows 10",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
