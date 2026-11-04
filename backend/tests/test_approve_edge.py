"""Approving: internal reports need no approval, approving twice is harmless, and wrong-state errors say what state the report is in."""

from .conftest import drain
from .test_client_reports import make_template, window


def gen(work, tpl):
    r = work.mgr.post(f"/report-templates/{tpl['id']}/generate", window(work))
    assert r.status_code == 202, r.text
    drain()
    return work.mgr.get(f"/report-runs/{r.json()['id']}").json()


def test_internal_runs_finish_as_ready_and_say_so_when_someone_tries_to_approve(work):
    run = gen(work, make_template(work, audience="internal", client_id=None, name="Internal weekly"))
    assert run["status"] == "ready" and run["audience"] == "internal" and run["downloads"]["xlsx"]
    r = work.mgr.post(f"/report-runs/{run['id']}/approve")
    assert r.status_code == 409 and r.json()["code"] == "internal_report"
    assert "do not need approval" in r.json()["message"]


def test_approving_twice_is_idempotent(work, owner_conn):
    run = gen(work, make_template(work))
    first = work.mgr.post(f"/report-runs/{run['id']}/approve")
    assert first.status_code == 200 and first.json()["status"] == "approved"
    second = work.mgr.post(f"/report-runs/{run['id']}/approve")  # double click / second tab
    assert second.status_code == 200 and second.json()["approved_at"] == first.json()["approved_at"]
    assert second.json()["approved_by"] == first.json()["approved_by"]
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'report.finalize'").fetchone()[0] == 1  # rendered once


def test_wrong_state_errors_name_the_state(work):

    run = gen(work, make_template(work))
    work.mgr.post(f"/report-runs/{run['id']}/redraft", {"note": "again"}).raise_for_status()  # queued, not drafted yet
    r = work.mgr.post(f"/report-runs/{run['id']}/approve")
    assert r.status_code == 409 and r.json()["code"] == "not_approvable" and "still being drafted" in r.json()["message"]
