"""Owner lock: the key is chosen at a hidden prompt and only its hash is stored; locked, every request but /health is
refused; only the right key unlocks."""

import pytest
from sqlalchemy import text

from app.core import owner_lock
from app.models.enums import UserRole
from scripts import owner_lock as cli

KEY = "correct horse battery"


@pytest.fixture
def run(db, monkeypatch):
    def go(action, *typed):
        answers = iter(typed)
        monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
        monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
        monkeypatch.setattr("sys.argv", ["owner_lock", action])
        code = cli.main()
        owner_lock._cache["at"] = 0.0  # re-read the state on the next request
        return code
    yield go
    db.execute(text("DELETE FROM owner_lock"))
    db.commit()
    owner_lock._cache.update(at=0.0, locked=False)


def test_lock_stops_everything_and_only_the_key_unlocks(client_for, db, run):
    agent, _ = client_for(UserRole.SALES_AGENT)
    assert run("lock", KEY) == 1  # no key set yet
    assert run("set", KEY, "something else") == 1 and run("set", "short", "short") == 1
    assert run("set", KEY, KEY) == 0
    stored = db.execute(text("SELECT key_hash FROM owner_lock")).scalar()
    assert KEY not in stored and stored.startswith("$argon2")  # only the hash
    assert run("lock", "wrong key guess") == 1 and agent.get("/auth/me").status_code == 200
    assert run("lock", KEY) == 0
    r = agent.get("/auth/me")
    assert r.status_code == 503 and "locked" in r.json()["detail"]
    assert agent.post("/auth/login", json={"email": "x@y.z", "password": "p"}).status_code == 503
    assert agent.get("/health").status_code == 200
    assert run("unlock", "wrong key guess") == 1 and agent.get("/auth/me").status_code == 503
    assert run("unlock", KEY) == 0 and agent.get("/auth/me").status_code == 200
    assert run("change", KEY, "a brand new owner key", "a brand new owner key") == 0
    assert run("lock", KEY) == 1 and run("lock", "a brand new owner key") == 0
