"""Step 6 clean-up: predictions relabelled PUBLISHED go back to PREDICTED; nothing legitimate is touched."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Company, Email, Person, Source
from scripts import contact_cleanup

LAUNDERED = "published at stored: the address spells the person's name (first.last)"


def setup(db):
    company = Company(name="Omega Foods", normalized_name="omega foods", domain="omega.example")
    source = Source(name="Official website · Team page", source_type="website", url="https://omega.example/team")
    db.add_all([company, source])
    db.flush()
    people = [Person(full_name=n, normalized_name=n.lower()) for n in ("Rana Saad", "Tony Rizk", "Lina Khoury")]
    db.add_all(people)
    db.flush()
    rana, tony, lina = (p.id for p in people)
    rows = {
        "laundered": Email(company_id=company.id, person_id=rana, email="rana.saad@omega.example", status="published",
                           provenance="public", evidence=LAUNDERED),
        # Tony already has a prediction: his laundered copy is a duplicate, removed
        "tony_predicted": Email(company_id=company.id, person_id=tony, email="tony@omega.example",
                                status="predicted", provenance="predicted"),
        "tony_laundered": Email(company_id=company.id, person_id=tony, email="tony.rizk@omega.example",
                                status="published", provenance="public", evidence=LAUNDERED),
        "sourced": Email(company_id=company.id, person_id=lina, email="lina.khoury@omega.example",
                         status="published", provenance="public", source_id=source.id, evidence=LAUNDERED),
        "human": Email(company_id=company.id, person_id=lina, email="lina@omega-private.example",
                       status="published", provenance="human_confirmed", evidence=LAUNDERED),
        "verified": Email(company_id=company.id, person_id=rana, email="r.saad@omega.example", status="verified",
                          provenance="verified", last_verified_at=datetime.now(timezone.utc)),
        "company_mailbox": Email(company_id=company.id, email="info@omega.example", status="published",
                                 provenance="public", evidence=LAUNDERED),
    }
    db.add_all(rows.values())
    db.commit()
    return {k: e.id for k, e in rows.items()}


def test_only_laundered_predictions_are_corrected(db, tmp_path):
    ids = setup(db)
    assert contact_cleanup.report(db)["affected"] == 2
    assert contact_cleanup.main([]) == 0  # dry run
    assert db.get(Email, ids["laundered"]).status == "published"
    assert contact_cleanup.main(["--apply"]) == 2  # no backup: refused
    backup = tmp_path / "live.dump"
    backup.write_bytes(b"PGDMP")
    assert contact_cleanup.main(["--apply", "--backup", str(backup)]) == 0
    db.expire_all()
    fixed = db.get(Email, ids["laundered"])
    assert (fixed.status, fixed.provenance) == ("predicted", "predicted")
    assert db.get(Email, ids["tony_laundered"]) is None  # one prediction per person
    for key in ("tony_predicted", "sourced", "human", "verified", "company_mailbox"):
        assert db.get(Email, ids[key]) is not None
    assert {db.get(Email, ids[k]).status for k in ("sourced", "human", "company_mailbox")} == {"published"}
    assert contact_cleanup.report(db)["affected"] == 0
    assert db.scalar(select(Email.provenance).where(Email.id == ids["human"])) == "human_confirmed"
