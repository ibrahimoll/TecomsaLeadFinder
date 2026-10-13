"""Lock or unlock LeadFinder with the owner key. The key is typed at a hidden prompt, never printed, logged or stored
(only its Argon2 hash is).

    docker compose exec backend python -m scripts.owner_lock status
    docker compose exec backend python -m scripts.owner_lock set      # first time: choose the owner key
    docker compose exec backend python -m scripts.owner_lock lock     # the website stops working
    docker compose exec backend python -m scripts.owner_lock unlock   # it works again
    docker compose exec backend python -m scripts.owner_lock change   # a new key (needs the current one)
"""

import argparse
import getpass
import sys
import time

from sqlalchemy import text

from app.core.owner_lock import state
from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal

MIN_LENGTH = 12


def _new_key() -> str | None:
    key = getpass.getpass(f"New owner key (min. {MIN_LENGTH} characters, hidden): ")
    if len(key) < MIN_LENGTH:
        print("Too short.", file=sys.stderr)
        return None
    if key != getpass.getpass("Repeat it: "):
        print("The two do not match.", file=sys.stderr)
        return None
    return key


def _write(sql: str, **params) -> None:
    with SessionLocal() as db:
        db.execute(text(sql), params)
        db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Lock or unlock LeadFinder with the owner key")
    parser.add_argument("action", choices=["status", "set", "lock", "unlock", "change"])
    args = parser.parse_args()
    current = state()
    if args.action == "status":
        print("No owner key set: LeadFinder is open." if current is None
              else "LeadFinder is LOCKED." if current[1] else "LeadFinder is unlocked.")
        return 0
    if args.action == "set":
        if current is not None:
            print("An owner key is already set (use: change).", file=sys.stderr)
            return 1
        key = _new_key()
        if not key:
            return 1
        _write("INSERT INTO owner_lock (id, key_hash, locked) VALUES (1, :h, false)", h=hash_password(key))
        print("Owner key set. LeadFinder stays unlocked until you run: lock")
        return 0
    if current is None:
        print("No owner key set yet (use: set).", file=sys.stderr)
        return 1
    if not verify_password(getpass.getpass("Owner key (hidden): "), current[0]):
        time.sleep(2)  # slows guessing
        print("Wrong key.", file=sys.stderr)
        return 1
    if args.action == "change":
        key = _new_key()
        if not key:
            return 1
        _write("UPDATE owner_lock SET key_hash = :h, changed_at = now() WHERE id = 1", h=hash_password(key))
        print("Owner key changed.")
        return 0
    _write("UPDATE owner_lock SET locked = :l, changed_at = now() WHERE id = 1", l=args.action == "lock")
    print("LeadFinder is LOCKED: the website stops within a few seconds." if args.action == "lock"
          else "LeadFinder is unlocked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
