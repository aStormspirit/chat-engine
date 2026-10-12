import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import WsAccountDep
from app.api.schemas import (
    ChatAction,
    ChatCommand,
    ErrorOut,
    EventOut,
    MessageOut,
    SnapshotOut,
)
from app.services.anon_chat import AnonChatService, ChatError, ChatEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.websocket("/accounts/{account_id}/chat/ws")
async def chat_socket(websocket: WebSocket, account: WsAccountDep) -> None:
    """Full-duplex chat channel for one account.

    Client sends `{"action": "start" | "stop" | "send", "text": "..."}`,
    server pushes a `snapshot` on connect and then `state` / `message` /
    `error` events.
    """
    await websocket.accept()
    service = account.service

    with service.subscribe() as events:
        await _send_model(websocket, _snapshot(service))

        receiver = asyncio.create_task(_receive_commands(websocket, service))
        sender = asyncio.create_task(_forward_events(websocket, events))
        done, pending = await asyncio.wait(
            {receiver, sender},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            exception = task.exception()
            if exception and not isinstance(exception, WebSocketDisconnect):
                logger.exception("WebSocket closed with an error", exc_info=exception)


def _snapshot(service: AnonChatService) -> SnapshotOut:
    return SnapshotOut(
        state=service.state,
        messages=[MessageOut.model_validate(message) for message in service.history()],
    )


async def _forward_events(websocket: WebSocket, events: asyncio.Queue[ChatEvent]) -> None:
    while True:
        event = await events.get()
        await _send_model(websocket, EventOut.from_event(event))


async def _receive_commands(websocket: WebSocket, service: AnonChatService) -> None:
    while True:
        payload = await websocket.receive_json()

        try:
            command = ChatCommand.model_validate(payload)
        except ValidationError as exc:
            await _send_model(websocket, ErrorOut(detail=exc.errors()[0]["msg"]))
            continue

        try:
            await _dispatch(command, service)
        except ChatError as exc:
            await _send_model(websocket, ErrorOut(detail=str(exc)))


async def _dispatch(command: ChatCommand, service: AnonChatService) -> None:
    match command.action:
        case ChatAction.START:
            await service.start_chat()
        case ChatAction.STOP:
            await service.stop_chat()
        case ChatAction.SEND:
            await service.send_message(command.text or "")


async def _send_model(websocket: WebSocket, model: ErrorOut | EventOut | SnapshotOut) -> None:
    await websocket.send_json(model.model_dump(mode="json"))
