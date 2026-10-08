from sqlalchemy import func, select

from app.models import Company, CompanyLocation, CompanyPerson, Email, OpportunityAnalysis, Person, Source
from scripts.seed_dev import seed_business


def test_dev_seed_is_marked_and_idempotent(db, client_for):
    seed_business(db)
    seed_business(db)  # second run adds nothing
    count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
    assert (count(Company), count(Person), count(CompanyPerson)) == (3, 11, 11)
    assert count(CompanyLocation) == 8 and count(OpportunityAnalysis) == 4
    assert all(c.name.endswith("(demo)") and c.domain.endswith(".example") for c in db.scalars(select(Company)))
    assert all(s.metadata_ == {"dev_seed": True} for s in db.scalars(select(Source)))
    assert db.scalar(select(func.count()).where(Email.status == "predicted", Email.last_verified_at.is_not(None))) == 0
    departments = set(db.scalars(select(CompanyPerson.department)))
    assert {"executive", "it", "finance", "marketing", "sales", "operations", "procurement", "hr"} <= departments
