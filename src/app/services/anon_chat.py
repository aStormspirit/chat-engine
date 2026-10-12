import asyncio
import logging
import re
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from telethon import TelegramClient

from app.config import Settings

logger = logging.getLogger(__name__)


class ChatState(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    CHATTING = "chatting"


class Direction(StrEnum):
    INCOMING = "in"
    OUTGOING = "out"
    SYSTEM = "system"


class EventType(StrEnum):
    STATE = "state"
    MESSAGE = "message"


class ChatError(RuntimeError):
    """Action is not allowed in the current chat state."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    seq: int
    direction: Direction
    text: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ChatEvent:
    type: EventType
    state: ChatState
    message: ChatMessage | None = None


class AnonChatService:
    """Drives an anonymous chat bot from a Telegram user account.

    The bot relays messages between two strangers, so the whole dialog happens
    in a single Telegram chat. Service notifications ("partner found", "partner
    left") are told apart from the partner's own messages by regex patterns,
    which keeps the service usable with different anonymous chat bots.

    Every state change and every message is published to subscribers, so
    WebSocket clients get updates without polling.
    """

    def __init__(self, client: TelegramClient, settings: Settings, bot_username: str) -> None:
        self._client = client
        self._bot_username = bot_username
        self._search_command = settings.anon_search_command
        self._stop_command = settings.anon_stop_command
        self._found_re = re.compile(settings.anon_partner_found_pattern, re.IGNORECASE)
        self._left_re = re.compile(settings.anon_partner_left_pattern, re.IGNORECASE)

        self._state = ChatState.IDLE
        self._history: deque[ChatMessage] = deque(maxlen=settings.history_limit)
        self._seq = 0
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[ChatEvent]] = set()

    @property
    def bot_username(self) -> str:
        return self._bot_username

    @property
    def state(self) -> ChatState:
        return self._state

    @property
    def last_seq(self) -> int:
        return self._seq

    def history(self, *, after_seq: int = 0, limit: int | None = None) -> list[ChatMessage]:
        messages = [message for message in self._history if message.seq > after_seq]
        return messages[-limit:] if limit is not None else messages

    @contextmanager
    def subscribe(self, *, maxsize: int = 100) -> Iterator[asyncio.Queue[ChatEvent]]:
        """Register a queue that receives every chat event until the caller leaves."""
        queue: asyncio.Queue[ChatEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def start_chat(self) -> ChatState:
        """Ask the bot for a new partner."""
        async with self._lock:
            if self._state is not ChatState.IDLE:
                raise ChatError(f"Chat is already active (state={self._state})")

            self._history.clear()
            await self._send(self._search_command)
            self._set_state(ChatState.SEARCHING)
            self._record(Direction.SYSTEM, f"→ {self._search_command}")

        logger.info("Looking for a partner via %s", self._bot_username)
        return self._state

    async def stop_chat(self) -> ChatState:
        """Leave the current dialog or cancel the search."""
        async with self._lock:
            if self._state is ChatState.IDLE:
                raise ChatError("There is no active chat to stop")

            await self._send(self._stop_command)
            self._set_state(ChatState.IDLE)
            self._record(Direction.SYSTEM, f"→ {self._stop_command}")

        logger.info("Chat stopped")
        return self._state

    async def send_message(self, text: str) -> ChatMessage:
        """Relay a message to the current partner."""
        async with self._lock:
            if self._state is not ChatState.CHATTING:
                raise ChatError(f"No partner connected (state={self._state})")

            await self._send(text)
            return self._record(Direction.OUTGOING, text)

    async def handle_bot_message(self, text: str) -> None:
        """Classify an incoming message from the anonymous chat bot."""
        async with self._lock:
            if self._found_re.search(text):
                self._set_state(ChatState.CHATTING)
                self._record(Direction.SYSTEM, text)
                logger.info("Partner found")
            elif self._left_re.search(text):
                self._set_state(ChatState.IDLE)
                self._record(Direction.SYSTEM, text)
                logger.info("Partner left")
            elif self._state is ChatState.CHATTING:
                self._record(Direction.INCOMING, text)
            else:
                self._record(Direction.SYSTEM, text)

    async def shutdown(self) -> None:
        if self._state is ChatState.IDLE:
            return
        try:
            await self._send(self._stop_command)
        except Exception:
            logger.exception("Failed to leave the chat on shutdown")
        self._set_state(ChatState.IDLE)

    async def _send(self, text: str) -> None:
        await self._client.send_message(self._bot_username, text)

    def _set_state(self, state: ChatState) -> None:
        if state is self._state:
            return
        self._state = state
        self._publish(ChatEvent(type=EventType.STATE, state=state))

    def _record(self, direction: Direction, text: str) -> ChatMessage:
        self._seq += 1
        message = ChatMessage(
            seq=self._seq,
            direction=direction,
            text=text,
            at=datetime.now(UTC),
        )
        self._history.append(message)
        self._publish(ChatEvent(type=EventType.MESSAGE, state=self._state, message=message))
        return message

    def _publish(self, event: ChatEvent) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue is full, dropping %s event", event.type)
