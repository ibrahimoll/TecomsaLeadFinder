from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.exceptions import InvalidCredentialsError
from app.core.rate_limit import login_limiter
from app.models.enums import UserRole
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.user import MeOut, PasswordChange, UserOut
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# The per-IP ceiling is higher because several people may share an office IP.
_IP_LIMIT_MULTIPLIER = 5


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    settings = get_settings()
    email = payload.email.strip().lower()
    ip = client_ip(request)
    window = settings.login_rate_limit_window_seconds
    email_key, ip_key = f"email:{email}", f"ip:{ip}"

    if login_limiter.is_limited(
        email_key, settings.login_rate_limit_attempts, window
    ) or login_limiter.is_limited(ip_key, settings.login_rate_limit_attempts * _IP_LIMIT_MULTIPLIER, window):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts. Please wait a few minutes and try again.",
            headers={"Retry-After": str(window)},
        )

    try:
        user, token, expires_at = auth_service.login(
            db, email, payload.password, ip=ip, user_agent=request.headers.get("user-agent")
        )
    except InvalidCredentialsError:
        login_limiter.record(email_key)
        login_limiter.record(ip_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    login_limiter.clear(email_key)
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return {"user": user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbSession) -> Response:
    """Revokes the server-side session (if any) and clears the cookie. Always succeeds."""
    settings = get_settings()
    auth_service.logout(db, request.cookies.get(settings.cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.cookie_name, path="/", httponly=True, secure=settings.secure_cookies, samesite="lax"
    )
    return response


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser):
    return {
        **UserOut.model_validate(user).model_dump(),
        "capabilities": {"manage_users": user.role == UserRole.ADMIN,
                         "run_imports": user.role in (UserRole.ADMIN, UserRole.SALES_MANAGER)},
    }


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: PasswordChange, request: Request, user: CurrentUser, db: DbSession) -> Response:
    """Change one's own password (the current one required, wrong guesses rate-limited like a login). The user's
    other sessions are signed out; this one stays. Audited without the value."""
    from sqlalchemy import update

    from app.core.security import hash_password, verify_password
    from app.models import UserSession

    settings = get_settings()
    key = f"password:{user.id}"
    if login_limiter.is_limited(key, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait a few minutes.")
    if not verify_password(payload.current_password, user.password_hash):
        login_limiter.record(key)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The current password is not correct")
    if payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a password different from the current one")
    login_limiter.clear(key)
    user.password_hash = hash_password(payload.new_password)
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None),
                                         UserSession.id != request.state.session_id)
               .values(revoked_at=datetime.now(timezone.utc)))
    audit_service.record(db, action=audit_service.AuditAction.USER_UPDATED, user_id=user.id, entity_type="user",
                         entity_id=user.id, metadata={"password_changed": True, "by": "self"})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
