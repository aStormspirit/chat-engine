from fastapi import APIRouter, Query, status

from app.api.deps import AccountDep
from app.api.schemas import ChatStatus, HistoryResponse, MessageOut, SendMessageRequest

router = APIRouter(prefix="/accounts/{account_id}/chat", tags=["chat"])


@router.post("/start", status_code=status.HTTP_202_ACCEPTED, summary="Начать чат")
async def start_chat(account: AccountDep) -> ChatStatus:
    """Попросить бота найти случайного собеседника."""
    state = await account.service.start_chat()
    return ChatStatus(state=state, last_seq=account.service.last_seq)


@router.post("/stop", summary="Закончить чат")
async def stop_chat(account: AccountDep) -> ChatStatus:
    """Выйти из текущего диалога или отменить поиск."""
    state = await account.service.stop_chat()
    return ChatStatus(state=state, last_seq=account.service.last_seq)


@router.post("/messages", status_code=status.HTTP_201_CREATED, summary="Отправить сообщение")
async def send_message(payload: SendMessageRequest, account: AccountDep) -> MessageOut:
    """Передать сообщение текущему собеседнику."""
    message = await account.service.send_message(payload.text)
    return MessageOut.model_validate(message)


@router.get("/messages", summary="Переписка")
async def get_messages(
    account: AccountDep,
    after_seq: int = Query(0, ge=0, description="Return only messages newer than this seq"),
    limit: int = Query(50, ge=1, le=500),
) -> HistoryResponse:
    """История переписки; `after_seq` позволяет опрашивать только новые сообщения."""
    messages = account.service.history(after_seq=after_seq, limit=limit)
    return HistoryResponse(
        state=account.service.state,
        messages=[MessageOut.model_validate(message) for message in messages],
    )


@router.get("/status", summary="Текущее состояние")
async def get_status(account: AccountDep) -> ChatStatus:
    return ChatStatus(state=account.service.state, last_seq=account.service.last_seq)
