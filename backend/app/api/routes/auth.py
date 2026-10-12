from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.exceptions import InvalidCredentialsError
from app.core.rate_limit import login_limiter
from app.models.enums import UserRole
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.user import MeOut, UserOut
from app.services import auth_service

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
