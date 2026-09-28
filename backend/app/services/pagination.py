from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = 25

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)).all())
    return items, total


def page_response(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
