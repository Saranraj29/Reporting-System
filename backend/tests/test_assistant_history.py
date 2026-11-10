"""Assistant conversations: new chat vs follow-up, the history list, opening, renaming, deleting, resuming and the length cap."""

import pytest

from app.ai.assistant import service

from .conftest import grant_assistant_to_members
from .test_assistant import ask, script


def chat(api, **body):
    """One question; returns the conversation id it landed in."""
    ev = ask(api, **body)
    return next(d["conversation_id"] for n, d in ev if n == "done")


@pytest.fixture(autouse=True)
def everyone_may_ask(work, owner_conn):
    grant_assistant_to_members(owner_conn)


def test_a_new_chat_is_separate_and_a_follow_up_stays_in_its_conversation(work):
    first = chat(work.admin, quick_action="my_due")
    follow_up = chat(work.admin, quick_action="my_due", conversation_id=first)
    fresh = chat(work.admin, quick_action="my_due")  # no conversation id = a new chat
    assert follow_up == first and fresh != first
    items = {c["id"]: c for c in work.admin.get("/assistant/conversations").json()["items"]}
    assert items[first]["message_count"] == 4 and items[fresh]["message_count"] == 2
    # a new chat does not inherit the old one's messages or context
    assert [m["role"] for m in work.admin.get(f"/assistant/conversations/{fresh}").json()["messages"]] == ["user", "assistant"]


def test_the_history_lists_newest_first_with_a_title_from_the_first_question(work, monkeypatch, owner_conn):
    script(monkeypatch, [{"action": "answer", "sentences": ["Hi."]}])
    long_question = "What is the state of the Apollo project and which of its tasks should I worry about this week please"
    a = chat(work.admin, message=long_question)
    b = chat(work.admin, quick_action="my_due")
    items = work.admin.get("/assistant/conversations").json()["items"]
    assert [i["id"] for i in items] == [b, a]  # the last one used is on top
    title = next(i["title"] for i in items if i["id"] == a)
    assert title.startswith("What is the state of the Apollo project") and title.endswith("…") and len(title) <= service.TITLE_LENGTH
    assert next(i["title"] for i in items if i["id"] == b)  # quick actions are titled by their request text
    # a conversation from before titles existed shows its first question
    owner_conn.execute("update ai_conversations set title = ''")
    assert next(i["title"] for i in work.admin.get("/assistant/conversations").json()["items"] if i["id"] == a).startswith("What is the state")


def test_conversations_are_private_to_their_owner(work):
    mine = chat(work.m1, quick_action="my_due")
    assert [i["id"] for i in work.m1.get("/assistant/conversations").json()["items"]] == [mine]
    assert work.m2.get("/assistant/conversations").json()["items"] == []
    for api in (work.m2, work.admin):  # not even a company admin can read someone else's chat
        assert api.get(f"/assistant/conversations/{mine}").status_code == 404
        assert api.patch(f"/assistant/conversations/{mine}", {"title": "mine now"}).status_code == 404
        assert api.delete(f"/assistant/conversations/{mine}").status_code == 404
    assert work.m1.get(f"/assistant/conversations/{mine}").status_code == 200
    # a follow-up that names somebody else's conversation starts a fresh one instead of joining it
    assert chat(work.m2, quick_action="my_due", conversation_id=mine) != mine


def test_rename(work):
    cid = chat(work.admin, quick_action="my_due")
    assert work.admin.patch(f"/assistant/conversations/{cid}", {"title": "  Weekly   review  "}).json()["title"] == "Weekly review"
    assert next(i["title"] for i in work.admin.get("/assistant/conversations").json()["items"]) == "Weekly review"
    assert work.admin.patch(f"/assistant/conversations/{cid}", {"title": ""}).status_code == 422
    assert work.admin.patch(f"/assistant/conversations/{cid}", {"title": "x" * 81}).status_code == 422


def test_delete_one_or_all_of_my_conversations_only(work, owner_conn):
    a, b = chat(work.admin, quick_action="my_due"), chat(work.admin, quick_action="my_due")
    other = chat(work.m1, quick_action="my_due")
    assert work.admin.delete(f"/assistant/conversations/{a}").status_code == 204
    assert owner_conn.execute("select count(*) from ai_messages where conversation_id = %s", (a,)).fetchone()[0] == 0  # the messages go with it
    assert [i["id"] for i in work.admin.get("/assistant/conversations").json()["items"]] == [b]
    assert work.admin.delete("/assistant/conversations").status_code == 204
    assert work.admin.get("/assistant/conversations").json()["items"] == []
    assert [i["id"] for i in work.m1.get("/assistant/conversations").json()["items"]] == [other]  # nobody else's history is touched


def test_the_panel_resumes_a_recent_chat_but_starts_fresh_after_a_long_gap(work, owner_conn):
    cid = chat(work.admin, quick_action="my_due")
    st = work.admin.get("/assistant/status").json()
    assert st["conversation_id"] == cid and len(st["messages"]) == 2  # still the same working session
    owner_conn.execute("update ai_conversations set updated_at = now() - interval '3 hours'")
    st = work.admin.get("/assistant/status").json()
    assert st["conversation_id"] is None and st["messages"] == []  # a blank chat ...
    assert [i["id"] for i in work.admin.get("/assistant/conversations").json()["items"]] == [cid]  # ... and the old one waits in the history


def test_a_conversation_has_a_length_cap_but_a_new_chat_is_always_possible(work, monkeypatch):
    monkeypatch.setattr(service, "MAX_CONVERSATION_MESSAGES", 4)
    cid = chat(work.admin, quick_action="my_due")
    chat(work.admin, quick_action="my_due", conversation_id=cid)  # 4 messages now
    r = work.admin.post("/assistant/chat", {"quick_action": "my_due", "conversation_id": cid})
    assert r.status_code == 409 and r.json()["code"] == "conversation_full"
    assert work.admin.get(f"/assistant/conversations/{cid}").json()["full"] is True
    assert chat(work.admin, quick_action="my_due") != cid
