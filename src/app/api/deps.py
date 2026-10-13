import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from app.accounts import Account, AccountManager, UnknownAccountError
from app.config import settings

WS_POLICY_VIOLATION = 1008

# Browsers cannot set headers on a WebSocket handshake, so they send the token
# as the subprotocol pair ["bearer", <token>] instead of in the URL.
WS_BEARER_SUBPROTOCOL = "bearer"

bearer_scheme = HTTPBearer(auto_error=False, description="Значение API_TOKEN")


def _is_valid_token(token: str | None) -> bool:
    if not settings.api_token:
        return True
    if not token:
        return False
    return secrets.compare_digest(token.encode(), settings.api_token.encode())


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Reject HTTP requests without a valid `Authorization: Bearer <token>`."""
    if not _is_valid_token(credentials.credentials if credentials else None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _websocket_token(websocket: WebSocket) -> str | None:
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()

    protocols = websocket.scope.get("subprotocols", [])
    if len(protocols) == 2 and protocols[0] == WS_BEARER_SUBPROTOCOL:
        return protocols[1]
    return None


def require_token_ws(websocket: WebSocket) -> None:
    """Reject the handshake unless a valid token is sent in a header or subprotocol."""
    if not _is_valid_token(_websocket_token(websocket)):
        raise WebSocketException(code=WS_POLICY_VIOLATION, reason="Invalid or missing API token")


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
