"""Round-trip tests for llm_conversations + llm_messages persistence."""
from __future__ import annotations

import pytest

from traffic_intel_phase3.poc_wadi_saqra.llm import conversations as convs
from traffic_intel_phase3.storage import db as _db_mod


@pytest.fixture
def fresh_db(tmp_path):
    """Spin up an isolated DB per test (the conversations module talks to
    the shared singleton by default; we bypass that by passing ``db=`` explicitly)."""
    path = tmp_path / "convs.db"
    db = _db_mod.Db(path)
    _db_mod.init_schema(db)
    # Seed a minimal user row so FK constraints don't block.
    db.execute(
        "INSERT INTO users (id, username, pw_hash, role) VALUES (1, 'tester', 'x', 'operator')"
    )
    yield db
    db.close()


def test_start_conversation_returns_unique_id(fresh_db):
    a = convs.start_conversation(
        user_id=1, username="tester", site_id="wadi_saqra",
        model="claude-sonnet-4-6", title="alpha", db=fresh_db,
    )
    b = convs.start_conversation(
        user_id=1, username="tester", site_id="wadi_saqra",
        model="claude-sonnet-4-6", title="beta", db=fresh_db,
    )
    assert a != b
    assert a.startswith("conv_")


def test_append_and_load_turns(fresh_db):
    cid = convs.start_conversation(
        user_id=1, username="tester", site_id="wadi_saqra",
        model="claude-sonnet-4-6", db=fresh_db,
    )
    convs.append_turn(cid, role="user", content="What's the queue on E?",
                     turn_index=0, tokens_in=8, tokens_out=0, db=fresh_db)
    convs.append_turn(
        cid, role="assistant",
        content=[
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "toolu_x", "name": "get_current_state", "input": {}},
        ],
        turn_index=1, tokens_in=0, tokens_out=42, db=fresh_db,
    )
    convs.append_turn(cid, role="user",
                     content=[{"type": "tool_result", "tool_use_id": "toolu_x", "content": "{...}"}],
                     turn_index=2, db=fresh_db)
    convs.append_turn(cid, role="assistant", content="Queue is 9 cars on E.",
                     turn_index=3, tokens_in=0, tokens_out=12, db=fresh_db)

    history = convs.load_history_for_api(cid, db=fresh_db)
    assert len(history) == 4
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "What's the queue on E?"
    assert history[1]["role"] == "assistant"
    assert isinstance(history[1]["content"], list)
    assert history[1]["content"][0]["type"] == "text"
    assert history[1]["content"][1]["type"] == "tool_use"


def test_token_totals_accumulate(fresh_db):
    cid = convs.start_conversation(
        user_id=1, username="tester", site_id="wadi_saqra",
        model="claude-sonnet-4-6", db=fresh_db,
    )
    convs.append_turn(cid, role="user", content="hi", turn_index=0,
                     tokens_in=10, tokens_out=0, db=fresh_db)
    convs.append_turn(cid, role="assistant", content="hello", turn_index=1,
                     tokens_in=0, tokens_out=20, db=fresh_db)
    row = fresh_db.query_one(
        "SELECT total_tokens_in, total_tokens_out FROM llm_conversations WHERE id = ?",
        (cid,),
    )
    assert row["total_tokens_in"] == 10
    assert row["total_tokens_out"] == 20


def test_get_conversation_owner_only(fresh_db):
    fresh_db.execute(
        "INSERT INTO users (id, username, pw_hash, role) VALUES (2, 'other', 'x', 'operator')"
    )
    cid = convs.start_conversation(
        user_id=1, username="tester", site_id=None,
        model="claude-sonnet-4-6", db=fresh_db,
    )
    convs.append_turn(cid, role="user", content="x", turn_index=0, db=fresh_db)
    # Owner can read.
    assert convs.get_conversation(cid, user_id=1, is_admin=False, db=fresh_db) is not None
    # Other user cannot.
    assert convs.get_conversation(cid, user_id=2, is_admin=False, db=fresh_db) is None
    # Admin can.
    assert convs.get_conversation(cid, user_id=2, is_admin=True, db=fresh_db) is not None


def test_delete_cascades_messages(fresh_db):
    cid = convs.start_conversation(
        user_id=1, username="tester", site_id=None,
        model="claude-sonnet-4-6", db=fresh_db,
    )
    convs.append_turn(cid, role="user", content="hi", turn_index=0, db=fresh_db)
    convs.append_turn(cid, role="assistant", content="hi back", turn_index=1, db=fresh_db)

    ok = convs.delete_conversation(cid, user_id=1, is_admin=False, db=fresh_db)
    assert ok is True
    msgs = fresh_db.query_all(
        "SELECT id FROM llm_messages WHERE conversation_id = ?", (cid,),
    )
    assert msgs == []


def test_next_turn_index_increments(fresh_db):
    cid = convs.start_conversation(
        user_id=1, username="tester", site_id=None,
        model="claude-sonnet-4-6", db=fresh_db,
    )
    assert convs.next_turn_index(cid, db=fresh_db) == 0
    convs.append_turn(cid, role="user", content="a", turn_index=0, db=fresh_db)
    assert convs.next_turn_index(cid, db=fresh_db) == 1
    convs.append_turn(cid, role="assistant", content="b", turn_index=1, db=fresh_db)
    assert convs.next_turn_index(cid, db=fresh_db) == 2
