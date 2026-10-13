"""Owner lock: while locked, every API request except /health is refused with 503, so the website stops working.

Only the owner key unlocks it (`python -m scripts.owner_lock unlock`, typed at a hidden prompt). The database keeps
the key's Argon2 hash, never the key. ponytail: a deterrent for app users and admins, not for whoever controls the
server or the code (they can drop the row); the state is re-read at most every CACHE_SECONDS.
"""

import time

import anyio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.http_security import _reject
from app.db.session import SessionLocal

CACHE_SECONDS = 3.0
OPEN_PATHS = ("/health",)
_cache = {"at": 0.0, "locked": False}


def state() -> tuple[str, bool] | None:
    """(key_hash, locked), or None before an owner key is set."""
    with SessionLocal() as db:
        try:
            row = db.execute(text("SELECT key_hash, locked FROM owner_lock WHERE id = 1")).first()
        except ProgrammingError:  # before migration 0034
            return None
    return (row[0], row[1]) if row else None


def is_locked() -> bool:
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        s = state()
        _cache.update(at=time.monotonic(), locked=bool(s and s[1]))
    return _cache["locked"]


class OwnerLockMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] not in OPEN_PATHS and await anyio.to_thread.run_sync(is_locked):
            await _reject(send, 503, "LeadFinder is locked by its owner.")
            return
        await self.app(scope, receive, send)
