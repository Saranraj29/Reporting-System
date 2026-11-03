import datetime as dt
import json

import pytest

from .conftest import drain, pdf_works

SECTIONS = ["Summary", "Work completed", "Hours by area", "Risks and blockers", "Next week"]


def make_template(work, **over):
    body = {
        "name": "Globex weekly update", "audience": "client", "base_report": "weekly", "format": "narrative",
        "sections": SECTIONS, "tone_instructions": "Formal, no internal names", "client_id": work.globex["id"], **over,
    }
    r = work.mgr.post("/report-templates", body)
    assert r.status_code == 201, r.text
    return r.json()


def window(work):
    return {"from": (work.today - dt.timedelta(days=6)).isoformat(), "to": work.today.isoformat()}


def generate(work, tpl):
    r = work.mgr.post(f"/report-templates/{tpl['id']}/generate", window(work))
    assert r.status_code == 202, r.text
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    return run


def enable_ai(monkeypatch, reply=None, record=None):
    from app.config import get_settings
    from app.services import ai

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()

    def fake(system, user):
        if record is not None:
            record.append((system, user))
        if isinstance(reply, Exception):
            raise reply
        return reply if reply is not None else json.dumps({"sections": {s: f"AI text for {s}" for s in SECTIONS}, "questions": []})

    monkeypatch.setattr(ai, "_call_model", fake)


# ------------------------------------------------------------------ templates
def test_template_validation(work):
    base = {"name": "t", "client_id": work.globex["id"], "sections": ["Summary"]}
    assert work.mgr.post("/report-templates", {**base, "base_report": "performance"}).json()["code"] == "invalid_base_report"
    assert work.mgr.post("/report-templates", {**base, "client_id": None}).json()["code"] == "client_required"
    assert work.mgr.post("/report-templates", {**base, "sections": []}).json()["code"] == "sections_required"
    assert work.mgr.post("/report-templates", {**base, "sections": ["A", "A"]}).json()["code"] == "duplicate_sections"
    assert work.mgr.post("/report-templates", {**base, "base_report": "nope"}).status_code == 400
    # internal templates may use the performance report, clients may not
    ok = work.mgr.post("/report-templates", {**base, "audience": "internal", "client_id": None, "base_report": "performance"})
    assert ok.status_code == 201
    assert work.lead.post("/report-templates", base).status_code == 403
    assert work.m1.get("/report-templates").status_code == 403


def test_template_crud(work):
    t = make_template(work)
    assert work.mgr.patch(f"/report-templates/{t['id']}", {"schedule": "weekly", "sections": ["Summary", "Next week"]}).json()["sections"] == ["Summary", "Next week"]
    assert work.mgr.patch(f"/report-templates/{t['id']}", {"base_report": "performance"}).status_code == 400
    assert [x["client_name"] for x in work.mgr.get("/report-templates").json()["items"]] == ["Globex"]
    assert work.mgr.delete(f"/report-templates/{t['id']}").status_code == 204


# ------------------------------------------------------------------ draft
def test_generate_without_ai_key_produces_a_figures_only_draft(work):
    run = generate(work, make_template(work))
    assert run["status"] == "drafted" and run["ai_provider"] == "figures_only"
    assert set(SECTIONS) <= set(run["ai_text"])
    assert "Ship login" in run["ai_text"]["Work completed"]
    assert "2" in run["ai_text"]["Summary"] or "hours" in run["ai_text"]["Summary"]
    f = run["figures"]
    assert "people" not in f  # no individual names in client figures
    assert {p["project"] for p in f["projects"]} == {"Apollo"}  # only the client's projects
    assert f["totals"]["hours"] == 9.0  # includes Olive's hours: a client report covers the whole project
    assert "Fix pipeline" not in str(f) and "Mia" not in str(f)


def test_only_ai_drafters_may_generate(work):
    t = make_template(work)
    assert work.lead.post(f"/report-templates/{t['id']}/generate").status_code == 403
    assert work.m1.post(f"/report-templates/{t['id']}/generate").status_code == 403


def test_ai_prompt_contains_only_aggregated_client_figures(work, monkeypatch):
    # Seed the kinds of data that must never reach the model
    work.m1.post(f"/tasks/{work.tasks['t1']['id']}/comments", {"body": "SECRET internal comment about pricing"}).raise_for_status()
    work.m1.put(f"/daily-status/{work.today}", {"did_today": "CONFIDENTIAL standup text"}).raise_for_status()
    calls = []
    enable_ai(monkeypatch, record=calls)
    run = generate(work, make_template(work))
    assert run["ai_provider"] == "anthropic" and run["ai_text"]["Summary"] == "AI text for Summary"
    system, user = calls[0]
    assert "ONLY the numbers" in system or "ONLY" in system
    assert "Globex weekly update" in user and "Formal, no internal names" in user
    assert "Apollo" in user and "Ship login" in user
    for forbidden in ("SECRET", "CONFIDENTIAL", "Mia", "Max", "Olive", "Leo", "Hermes", "Fix pipeline", "acme.com", "people"):
        assert forbidden not in user, forbidden


def test_model_questions_and_missing_sections_are_surfaced(work, monkeypatch):
    enable_ai(monkeypatch, reply='Sure! {"sections": {"Summary": "Good week."}, "questions": ["What is the delivery date?"]}')
    run = generate(work, make_template(work))
    assert run["ai_text"]["Summary"] == "Good week."
    qs = run["ai_text"]["_questions"]
    assert "What is the delivery date?" in qs and any("Work completed" in q for q in qs)


def test_edit_draft_inline_and_validation(work):
    run = generate(work, make_template(work))
    r = work.mgr.patch(f"/report-runs/{run['id']}", {"ai_text": {"Summary": "Edited by a human."}})
    assert r.status_code == 200 and r.json()["ai_text"]["Summary"] == "Edited by a human."
    assert work.mgr.patch(f"/report-runs/{run['id']}", {"ai_text": {"Bogus": "x"}}).status_code == 400


def test_redraft_with_note_reruns_the_draft(work, monkeypatch):
    calls = []
    enable_ai(monkeypatch, record=calls)
    run = generate(work, make_template(work))
    r = work.mgr.post(f"/report-runs/{run['id']}/redraft", {"note": "shorter, mention the delayed API work"})
    assert r.status_code == 202
    assert work.mgr.get(f"/report-runs/{run['id']}").json()["status"] == "queued"
    drain()
    assert len(calls) == 2
    assert "mention the delayed API work" in calls[1][1] and "PREVIOUS DRAFT" in calls[1][1]
    assert work.mgr.get(f"/report-runs/{run['id']}").json()["status"] == "drafted"


def test_ai_failure_retries_three_times_then_fails_and_figures_only_still_works(work, monkeypatch, owner_conn):
    calls = []
    enable_ai(monkeypatch, reply=RuntimeError("provider down"), record=calls)
    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert len(calls) == 3 and run["status"] == "failed" and "provider down" in run["error"]
    from app.services import mail

    assert any("Report failed" in m["subject"] and m["to"] == "maya.manager@acme.com" for m in mail.outbox)
    # the update can still go out without narrative
    assert work.mgr.post(f"/report-runs/{run['id']}/redraft", {"figures_only": True}).status_code == 202
    drain()
    again = work.mgr.get(f"/report-runs/{run['id']}").json()
    assert again["status"] == "drafted" and again["ai_provider"] == "figures_only" and "Ship login" in again["ai_text"]["Work completed"]


# ------------------------------------------------------------------ approve + share
def contact_id(work):
    return work.mgr.get(f"/clients/{work.globex['id']}/contacts").json()["items"][0]["id"]


def test_cannot_approve_without_permission_or_share_before_approval(work):
    run = generate(work, make_template(work))
    assert work.lead.post(f"/report-runs/{run['id']}/approve").status_code == 403
    r = work.mgr.post(f"/report-runs/{run['id']}/share", {"contact_ids": [contact_id(work)]})
    assert r.status_code == 409 and r.json()["code"] == "not_approved"


@pytest.mark.skipif(not pdf_works(), reason="Chromium not available")
def test_full_flow_approve_share_and_public_page(work):
    from app.services import mail

    run = generate(work, make_template(work))
    work.mgr.patch(f"/report-runs/{run['id']}", {"ai_text": {"Summary": "A calm week for Globex."}}).raise_for_status()
    assert any("Draft ready for review" in m["subject"] for m in mail.outbox)  # requester + approvers are notified
    ok = work.mgr.post(f"/report-runs/{run['id']}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approved_at"]
    assert ok.json()["approved_by"] == work.mgr.user_id
    assert work.mgr.post(f"/report-runs/{run['id']}/approve").status_code == 409
    drain()  # the worker renders the final files
    done = work.mgr.get(f"/report-runs/{run['id']}").json()
    assert all(done["downloads"][f] for f in ("pdf", "docx", "xlsx"))

    # recipients must be the client's contacts
    bad = work.mgr.post(f"/report-runs/{run['id']}/share", {"contact_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert bad.status_code == 400
    shared = work.mgr.post(f"/report-runs/{run['id']}/share", {"contact_ids": [contact_id(work)]})
    assert shared.status_code == 201
    drain()
    sent = [m for m in mail.outbox if m["to"] == "gina@globex.com"]
    assert sent and sent[0]["attachments"] == ["report.pdf"] and "/shared/" in sent[0]["text"]
    assert work.mgr.get(f"/report-runs/{run['id']}").json()["status"] == "sent"

    token = sent[0]["text"].split("/shared/")[1].split()[0]
    assert len(token) >= 43  # random 32-byte token
    assert work.mgr.get(f"/report-runs/{run['id']}/shares").json()["items"][0]["viewed_at"] is None
    page = work.client.get(f"/api/v1/shared/{token}")  # no login
    assert page.status_code == 200
    j = page.json()
    assert "A calm week for Globex." in j["html"] and j["client_name"] == "Globex" and "Mia" not in j["html"]
    assert work.client.get(j["pdf_url"]).content.startswith(b"%PDF")
    assert work.mgr.get(f"/report-runs/{run['id']}/shares").json()["items"][0]["viewed_at"]  # view logged


def test_shared_links_expire_and_can_be_revoked(work, owner_conn):
    run = generate(work, make_template(work))
    work.mgr.post(f"/report-runs/{run['id']}/approve").raise_for_status()
    # skip real PDF rendering for this test: pretend final files exist
    owner_conn.execute("UPDATE report_runs SET file_url_pdf = 'x/y/report.pdf' WHERE id = %s", (run["id"],))
    shares = work.mgr.post(f"/report-runs/{run['id']}/share", {"contact_ids": [contact_id(work)], "expires_in_days": 30}).json()["items"]
    token = owner_conn.execute("SELECT token FROM report_shares").fetchone()[0]
    assert work.client.get(f"/api/v1/shared/{token}").status_code == 200
    owner_conn.execute("UPDATE report_shares SET expires_at = now() - interval '1 minute'")
    gone = work.client.get(f"/api/v1/shared/{token}")
    assert gone.status_code == 410 and gone.json()["code"] == "link_expired"
    owner_conn.execute("UPDATE report_shares SET expires_at = now() + interval '1 day'")
    assert work.client.get(f"/api/v1/shared/{token}").status_code == 200
    assert work.mgr.delete(f"/report-runs/{run['id']}/shares/{shares[0]['id']}").status_code == 204
    assert work.client.get(f"/api/v1/shared/{token}").status_code == 410
    assert work.client.get("/api/v1/shared/not-a-real-token").status_code == 404


def test_sharing_requires_its_own_permission(work):
    run = generate(work, make_template(work))
    work.mgr.post(f"/report-runs/{run['id']}/approve").raise_for_status()
    work.admin.post("/roles", {"name": "Approver", "permissions": ["report.approve", "report.ai.draft"]}).raise_for_status()
    from .conftest import add_user

    appr = add_user(work.admin, "Ann Approver", "Approver")
    assert appr.post(f"/report-runs/{run['id']}/share", {"contact_ids": [contact_id(work)]}).status_code == 403


def test_internal_templates_skip_approval(work):
    t = make_template(work, audience="internal", client_id=None, name="Internal weekly")
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert run["status"] == "ready" and run["downloads"]["xlsx"]
    assert work.mgr.post(f"/report-runs/{run['id']}/approve").status_code == 409


def test_client_run_list_filters(work):
    generate(work, make_template(work))
    work.mgr.post("/reports/weekly/export", {}, params={"format": "xlsx"})
    assert work.mgr.get("/report-runs", params={"kind": "client"}).json()["total"] == 1
    assert work.mgr.get("/report-runs", params={"kind": "export"}).json()["total"] == 1
    assert work.mgr.get("/report-runs", params={"status": "drafted"}).json()["total"] == 1


def test_scheduled_template_generates_a_draft_and_notifies_approvers(work):
    from app.services import mail
    from app.worker import schedule_tick

    t = make_template(work, schedule="weekly")
    friday = dt.datetime(2026, 11, 6, 16, 5, tzinfo=dt.UTC)
    assert schedule_tick(friday) >= 1
    drain()
    runs = work.mgr.get("/report-runs", params={"kind": "client"}).json()["items"]
    assert len(runs) == 1 and runs[0]["status"] == "drafted" and runs[0]["template_id"] == t["id"]
    assert runs[0]["requested_by"] is None
    assert any("Draft ready for review" in m["subject"] for m in mail.outbox)
    before = len(runs)
    schedule_tick(friday + dt.timedelta(minutes=30))  # same day: deduped
    drain()
    assert len(work.mgr.get("/report-runs", params={"kind": "client"}).json()["items"]) == before
    # a Thursday never fires a weekly template
    schedule_tick(dt.datetime(2026, 11, 12, 16, 5, tzinfo=dt.UTC))
    drain()
    assert len(work.mgr.get("/report-runs", params={"kind": "client"}).json()["items"]) == before
