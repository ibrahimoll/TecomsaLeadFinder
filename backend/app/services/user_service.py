from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services import audit_service, auth_service
from app.services.audit_service import AuditAction
from app.services.pagination import PageParams, paginate


def _email_taken(db: Session, email: str, exclude_id: int | None = None) -> bool:
    stmt = select(User.id).where(User.email == email)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) is not None


def list_users(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    return paginate(db, stmt.order_by(User.name, User.id), params)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


def create_user(db: Session, actor: User | None, data: UserCreate) -> User:
    """Create a user. `actor` is None only for bootstrap scripts (initial admin, dev seed)."""
    email = str(data.email).lower()
    if _email_taken(db, email):
        raise ConflictError("A user with this email already exists")
    user = User(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
        role=data.role,
        odoo_user_id=data.odoo_user_id,
        is_active=data.is_active,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        action=AuditAction.USER_CREATED,
        user_id=actor.id if actor else None,
        entity_type="user",
        entity_id=user.id,
        metadata={"email": email, "role": data.role.value, "via": "api" if actor else "script"},
    )
    db.commit()
    return user


def update_user(db: Session, actor: User, user_id: int, data: UserUpdate) -> User:
    user = get_user(db, user_id)
    changes = data.model_dump(exclude_unset=True)

    if user.id == actor.id:
        if changes.get("is_active") is False:
            raise BusinessRuleError("You cannot deactivate your own account")
        if "role" in changes and changes["role"] != user.role:
            raise BusinessRuleError("You cannot change your own role")

    if "email" in changes:
        changes["email"] = str(changes["email"]).lower()
        if _email_taken(db, changes["email"], exclude_id=user.id):
            raise ConflictError("A user with this email already exists")

    changed: dict[str, dict] = {}
    for field in ("name", "email", "role", "odoo_user_id"):
        if field in changes and changes[field] != getattr(user, field):
            changed[field] = {"from": getattr(user, field), "to": changes[field]}
            setattr(user, field, changes[field])

    password_changed = False
    if changes.get("password"):
        user.password_hash = hash_password(changes["password"])
        password_changed = True
        auth_service.revoke_all_sessions(db, user.id)

    if changed or password_changed:
        metadata: dict = {"changes": changed}
        if password_changed:
            metadata["password_changed"] = True  # never log the value
        audit_service.record(
            db,
            action=AuditAction.USER_UPDATED,
            user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            metadata=metadata,
        )

    if "is_active" in changes and changes["is_active"] != user.is_active:
        user.is_active = changes["is_active"]
        if not user.is_active:
            auth_service.revoke_all_sessions(db, user.id)
        audit_service.record(
            db,
            action=AuditAction.USER_ACTIVATED if user.is_active else AuditAction.USER_DEACTIVATED,
            user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            metadata={"email": user.email},
        )

    db.commit()
    db.refresh(user)
    return user
