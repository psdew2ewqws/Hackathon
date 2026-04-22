"""User persistence + bcrypt password hashing. Uses the shared SQLite handle."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import bcrypt

from ..storage.db import Db, get_db

Role = Literal["viewer", "operator", "admin"]
ROLES: tuple[Role, ...] = ("viewer", "operator", "admin")


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    role: Role


class UsersRepository:
    def __init__(self, db: Db | None = None) -> None:
        self.db = db or get_db()

    def create(self, username: str, password: str, role: Role) -> UserRecord:
        if role not in ROLES:
            raise ValueError(f"bad role: {role}")
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur = self.db.execute(
            "INSERT INTO users(username, pw_hash, role) VALUES(?,?,?)",
            (username, pw_hash, role),
        )
        return UserRecord(id=int(cur.lastrowid), username=username, role=role)

    def find(self, username: str) -> tuple[UserRecord, str] | None:
        row = self.db.query_one(
            "SELECT id, username, role, pw_hash FROM users WHERE username = ?",
            (username,),
        )
        if not row:
            return None
        return UserRecord(id=row["id"], username=row["username"], role=row["role"]), row["pw_hash"]

    def verify(self, username: str, password: str) -> UserRecord | None:
        found = self.find(username)
        if not found:
            return None
        user, pw_hash = found
        if bcrypt.checkpw(password.encode(), pw_hash.encode()):
            return user
        return None

    def list(self) -> list[UserRecord]:
        rows = self.db.query_all("SELECT id, username, role FROM users ORDER BY id")
        return [UserRecord(id=r["id"], username=r["username"], role=r["role"]) for r in rows]

    def delete(self, username: str) -> int:
        cur = self.db.execute("DELETE FROM users WHERE username = ?", (username,))
        return cur.rowcount


def ensure_default_users(repo: UsersRepository | None = None) -> list[UserRecord]:
    """Seed ``viewer``/``operator``/``admin`` accounts on first boot.

    Passwords come from the env (``TRAFFIC_INTEL_<ROLE>_PW``) if set, otherwise
    fall back to fixed demo values. Idempotent — existing usernames are kept as-is.
    """
    repo = repo or UsersRepository()
    defaults = {
        "viewer":   os.getenv("TRAFFIC_INTEL_VIEWER_PW",   "viewer123"),
        "operator": os.getenv("TRAFFIC_INTEL_OPERATOR_PW", "operator123"),
        "admin":    os.getenv("TRAFFIC_INTEL_ADMIN_PW",    "admin123"),
    }
    out: list[UserRecord] = []
    for username, password in defaults.items():
        if repo.find(username):
            continue
        out.append(repo.create(username, password, role=username))  # type: ignore[arg-type]
    return out
