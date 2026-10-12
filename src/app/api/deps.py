from typing import Annotated

from fastapi import Depends, HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection

from app.accounts import Account, AccountManager, UnknownAccountError

WS_POLICY_VIOLATION = 1008


def get_manager(connection: HTTPConnection) -> AccountManager:
    return connection.app.state.accounts


ManagerDep = Annotated[AccountManager, Depends(get_manager)]


def get_account(account_id: str, manager: ManagerDep) -> Account:
    """Resolve an account for HTTP routes."""
    try:
        account = manager.get(account_id)
    except UnknownAccountError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown account '{account_id}'",
        ) from None

    if not account.authorized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Account '{account_id}' is not authorized, run `python -m app login {account_id}`"
            ),
        )
    return account


def get_account_ws(account_id: str, manager: ManagerDep) -> Account:
    """Resolve an account for WebSocket routes.

    HTTPException cannot be delivered over an upgraded connection, so the
    handshake is rejected with a policy-violation close code instead.
    """
    try:
        account = manager.get(account_id)
    except UnknownAccountError:
        raise WebSocketException(
            code=WS_POLICY_VIOLATION,
            reason=f"Unknown account '{account_id}'",
        ) from None

    if not account.authorized:
        raise WebSocketException(
            code=WS_POLICY_VIOLATION,
            reason=f"Account '{account_id}' is not authorized",
        )
    return account


AccountDep = Annotated[Account, Depends(get_account)]
WsAccountDep = Annotated[Account, Depends(get_account_ws)]
