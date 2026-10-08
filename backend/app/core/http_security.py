"""HTTP-level protections, applied to every request before routing (pure ASGI, no buffering).

* CSRF: authentication is a cookie, so a state-changing request (POST/PUT/PATCH/DELETE) that carries
  it must come from LeadFinder itself. Browsers always send `Origin` on cross-origin requests and
  `Sec-Fetch-Site` on all modern requests; either one naming another site is refused. Requests
  without a session cookie (login, server-to-server clients) are not affected: they cannot ride on a
  victim's session.
* Body size: requests larger than the limit are refused with 413 before anything is parsed (also
  chunked bodies without Content-Length).
* Response headers: JSON responses are never cached, sniffed or framed.
"""

import json
from typing import Any

from app.core.config import get_settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_BODY_LIMIT = 1024 * 1024  # 1 MB: every JSON body LeadFinder accepts is far smaller
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cross-origin-resource-policy", b"same-origin"),
]


async def _reject(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            *_SECURITY_HEADERS]})
    await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


def allowed_origins() -> set[str]:
    """The app's own origins. Development also accepts the localhost aliases of the frontend port."""
    s = get_settings()
    allowed = set(s.cors_origins)
    if not s.is_production:
        from urllib.parse import urlsplit

        for origin in s.cors_origins:
            port = urlsplit(origin).port
            allowed |= {f"http://localhost:{port}", f"http://127.0.0.1:{port}"} if port else set()
    return allowed


def cross_site(headers: dict[bytes, bytes], allowed: set[str]) -> bool:
    origin = headers.get(b"origin", b"").decode("latin1").strip().rstrip("/")
    if origin:
        return origin not in allowed  # includes "null" (sandboxed frames, data: URLs)
    site = headers.get(b"sec-fetch-site", b"").decode("latin1").strip().lower()
    return site not in ("", "same-origin", "none")


class SecurityMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        s = get_settings()
        headers = dict(scope["headers"])
        method = scope.get("method", "GET")

        if method in UNSAFE:
            cookie = headers.get(b"cookie", b"").decode("latin1")
            if f"{s.cookie_name}=" in cookie and cross_site(headers, allowed_origins()):
                return await _reject(send, 403, "Cross-site request refused.")

        limit = DEFAULT_BODY_LIMIT
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            return await _reject(send, 413, "Request body too large.")

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        started = False

        async def secure_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in existing]
                if s.is_production:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        try:
            await self.app(scope, limited_receive, secure_send)
        except _TooLarge:
            if not started:
                await _reject(send, 413, "Request body too large.")
