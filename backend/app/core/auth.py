"""Admin-panel API key gate.

When `auth_enabled` is off (the default), every route is open. When it is on,
admin `/api/*` routes require a valid key. Model traffic stays public:
`/v1/chat/completions`, `/v1/messages`, `/v1/models`.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services import api_key_service, settings_service

PUBLIC_EXACT = frozenset({
    "/api/health",
    "/api/health/live",
    "/api/auth/verify",
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/messages/count_tokens",
    "/v1/models",
})

INVALID_KEY_DETAIL = "Invalid API key"


def is_public_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in {item.rstrip("/") for item in PUBLIC_EXACT}:
        return True
    if path.startswith("/assets/") or path == "/qoder.svg":
        return True
    # SPA and any non-API path — the panel JS is public; the JSON behind
    # it is not (when auth is on).
    if not path.startswith("/api/") and not path.startswith("/v1/"):
        return True
    return False


def extract_api_key(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    header = (request.headers.get("x-api-key") or "").strip()
    if header:
        return header
    query = (request.query_params.get("api_key") or "").strip()
    if query:
        return query
    return None


class AuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        if request.method == "OPTIONS" or is_public_path(request.url.path):
            await self.app(scope, receive, send)
            return

        if not bool(settings_service.get("auth_enabled")):
            await self.app(scope, receive, send)
            return

        key = extract_api_key(request)
        if not await api_key_service.is_valid(key):
            response = JSONResponse(
                status_code=401,
                content={"detail": INVALID_KEY_DETAIL},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
