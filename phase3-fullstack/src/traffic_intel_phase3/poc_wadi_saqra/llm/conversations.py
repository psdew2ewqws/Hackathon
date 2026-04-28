"""SQLite persistence for LLM conversations.

Stores one row per top-level message (user or assistant). When a turn
involves tool use, the assistant row's ``content`` is a JSON-encoded
Anthropic content-block list; otherwise it's plain text. The same
shape goes back into ``messages`` on the next API call.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from ...storage.db import Db, get_db


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def _serialise_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def _deserialise_content(blob: str) -> Any:
    if not blob:
        return ""
    if blob.startswith("[") or blob.startswith("{"):
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return blob
    return blob


def start_conversation(
    *,
    user_id: int,
    username: str,
    site_id: str | None,
    model: str,
    title: str | None = None,
    db: Db | None = None,
) -> str:
    db = db or get_db()
    conv_id = f"conv_{uuid.uuid4().hex[:24]}"
    now = _now_iso()
    db.execute(
        "INSERT INTO llm_conversations "
        "(id, user_id, username, site_id, created_at, updated_at, title, model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (conv_id, user_id, username, site_id, now, now, title, model),
    )
    return conv_id


def append_turn(
    conversation_id: str,
    *,
    role: str,
    content: Any,
    turn_index: int,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    db: Db | None = None,
) -> None:
    if role not in ("user", "assistant"):
        raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
    db = db or get_db()
    db.execute(
        "INSERT INTO llm_messages "
        "(conversation_id, turn_index, role, content, tokens_in, tokens_out) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, turn_index, role, _serialise_content(content), tokens_in, tokens_out),
    )
    db.execute(
        "UPDATE llm_conversations "
        "SET updated_at = ?, "
        "    total_tokens_in = total_tokens_in + COALESCE(?, 0), "
        "    total_tokens_out = total_tokens_out + COALESCE(?, 0) "
        "WHERE id = ?",
        (_now_iso(), tokens_in, tokens_out, conversation_id),
    )


def next_turn_index(conversation_id: str, db: Db | None = None) -> int:
    db = db or get_db()
    row = db.query_one(
        "SELECT COALESCE(MAX(turn_index), -1) AS max_idx FROM llm_messages WHERE conversation_id = ?",
        (conversation_id,),
    )
    return int(row["max_idx"]) + 1 if row else 0


def load_history_for_api(
    conversation_id: str,
    *,
    max_messages: int = 50,
    db: Db | None = None,
) -> list[dict[str, Any]]:
    """Return messages in Anthropic API format, newest ``max_messages`` only."""
    db = db or get_db()
    rows = db.query_all(
        "SELECT role, content FROM llm_messages "
        "WHERE conversation_id = ? "
        "ORDER BY turn_index ASC, id ASC "
        "LIMIT ?",
        (conversation_id, max_messages),
    )
    return [
        {"role": r["role"], "content": _deserialise_content(r["content"])}
        for r in rows
    ]


def get_conversation(
    conversation_id: str,
    *,
    user_id: int,
    is_admin: bool,
    db: Db | None = None,
) -> dict[str, Any] | None:
    db = db or get_db()
    where = "id = ?" if is_admin else "id = ? AND user_id = ?"
    params: tuple = (conversation_id,) if is_admin else (conversation_id, user_id)
    head = db.query_one(
        f"SELECT id, user_id, username, site_id, created_at, updated_at, title, "
        f"       model, total_tokens_in, total_tokens_out "
        f"FROM llm_conversations WHERE {where}",
        params,
    )
    if not head:
        return None
    msgs = db.query_all(
        "SELECT turn_index, ts, role, content, tokens_in, tokens_out "
        "FROM llm_messages WHERE conversation_id = ? "
        "ORDER BY turn_index ASC, id ASC",
        (conversation_id,),
    )
    return {
        **head,
        "messages": [
            {
                "turn_index": m["turn_index"],
                "ts": m["ts"],
                "role": m["role"],
                "content": _deserialise_content(m["content"]),
                "tokens_in": m["tokens_in"],
                "tokens_out": m["tokens_out"],
            }
            for m in msgs
        ],
    }


def list_user_conversations(
    *,
    user_id: int,
    is_admin: bool,
    limit: int = 20,
    include_all: bool = False,
    db: Db | None = None,
) -> list[dict[str, Any]]:
    db = db or get_db()
    if is_admin and include_all:
        rows = db.query_all(
            "SELECT id, user_id, username, title, model, created_at, updated_at, "
            "       total_tokens_in, total_tokens_out "
            "FROM llm_conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = db.query_all(
            "SELECT id, user_id, username, title, model, created_at, updated_at, "
            "       total_tokens_in, total_tokens_out "
            "FROM llm_conversations WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        )
    return rows


def delete_conversation(
    conversation_id: str,
    *,
    user_id: int,
    is_admin: bool,
    db: Db | None = None,
) -> bool:
    db = db or get_db()
    where = "id = ?" if is_admin else "id = ? AND user_id = ?"
    params: tuple = (conversation_id,) if is_admin else (conversation_id, user_id)
    row = db.query_one(f"SELECT id FROM llm_conversations WHERE {where}", params)
    if not row:
        return False
    with db.transaction() as conn:
        conn.execute("DELETE FROM llm_messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM llm_conversations WHERE id = ?", (conversation_id,))
    return True


def set_title_if_unset(
    conversation_id: str,
    *,
    title: str,
    db: Db | None = None,
) -> None:
    db = db or get_db()
    db.execute(
        "UPDATE llm_conversations SET title = ? WHERE id = ? AND (title IS NULL OR title = '')",
        (title[:120], conversation_id),
    )
