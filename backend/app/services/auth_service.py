import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import InvalidCredentialsError
from app.core.security import create_session_token, decode_session_token, verify_password
from app.models import User, UserSession
from app.services import audit_service
from app.services.audit_service import AuditAction


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login(
    db: Session, email: str, password: str, *, ip: str | None, user_agent: str | None
) -> tuple[User, str, datetime]:
    """Verify credentials and open a server-side session. Returns (user, token, expires_at)."""
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    reason = None
    if user is None:
        verify_password(password, None)  # equalise timing
        reason = "unknown_email"
    elif not verify_password(password, user.password_hash):
        reason = "wrong_password"
    elif not user.is_active:
        reason = "inactive_user"

    if reason is not None:
        audit_service.record(
            db,
            action=AuditAction.LOGIN_FAILED,
            user_id=user.id if user else None,
            entity_type="user",
            entity_id=user.id if user else None,
            metadata={"email": email[:320], "reason": reason, "ip": ip},
        )
        db.commit()
        raise InvalidCredentialsError()

    assert user is not None
    now = _now()
    expires_at = now + timedelta(minutes=get_settings().session_expire_minutes)
    session = UserSession(
        id=secrets.token_hex(32),
        user_id=user.id,
        expires_at=expires_at,
        ip_address=ip,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    user.last_login_at = now
    audit_service.record(
        db,
        action=AuditAction.LOGIN,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"ip": ip},
    )
    db.commit()
    return user, create_session_token(user.id, session.id, expires_at), expires_at


def resolve_session(db: Session, token: str) -> tuple[User, UserSession] | None:
    payload = decode_session_token(token)
    if payload is None:
        return None
    session = db.get(UserSession, payload["sid"])
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= _now()
        or str(session.user_id) != str(payload["sub"])
    ):
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user, session


def logout(db: Session, token: str | None) -> None:
    if not token:
        return
    resolved = resolve_session(db, token)
    if resolved is None:
        return
    user, session = resolved
    session.revoked_at = _now()
    audit_service.record(
        db, action=AuditAction.LOGOUT, user_id=user.id, entity_type="user", entity_id=user.id
    )
    db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    """Called when a user is deactivated or their password is reset (caller commits)."""
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
