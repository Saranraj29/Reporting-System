"""AI reports: request -> structure preview -> approve -> finished report (md / docx / xlsx / pdf)."""

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import pytest

from .conftest import drain, pdf_works

SAMPLE = (Path(__file__).resolve().parents[2] / "docs" / "examples" / "project-visibility-report.md").read_text()


def window(work):
    return {"period_start": (work.today - dt.timedelta(days=6)).isoformat(), "period_end": work.today.isoformat()}


def create(api, work, **over):
    r = api.post("/ai-reports", {"request": "Weekly report for leadership", **window(work), **over})
    assert r.status_code == 202, r.text
    drain()
    return api.get(f"/ai-reports/{r.json()['id']}").json()


def make_owner(work, user, project=None):
    work.admin.put(f"/projects/{(project or work.project)['id']}/members", {"user_ids": [], "owner_ids": [user.user_id]}).raise_for_status()


def fake_llm(monkeypatch, plan=None, record=None, write=None):
    """Pretend an AI provider is configured. plan: outline dict (or Exception); write: fn(items)->{key: text} (or Exception)."""
    from app.config import get_settings
    from app.services import ai
    from app.services.airep import writer

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()

    def fake(system, user, cfg=None):
        if record is not None:
            record.append((system, user))
        if system == writer.PLAN_SYSTEM:
            if isinstance(plan, Exception):
                raise plan
            return json.dumps(plan)
        if isinstance(write, Exception):
            raise write
        items = json.loads(user.split("ITEMS:\n", 1)[1].split("\n\nCHANGE", 1)[0].split("\n\nPREVIOUS", 1)[0])
        texts = write(items) if write else {i["key"]: f"Text for {i['key']}" for i in items}
        return json.dumps({"items": [{"key": k, "text": v} for k, v in texts.items()]})

    monkeypatch.setattr(ai, "_call_model", fake)


# ------------------------------------------------------------------ access
def test_access_rules(work):
    assert work.m1.get("/ai-reports/options").status_code == 403
    assert work.m1.post("/ai-reports", window(work)).status_code == 403
    assert work.admin.get("/ai-reports/options").json()["all_projects"] is True
    assert work.m1.get("/me").json()["owns_projects"] is False
    make_owner(work, work.m1)
    assert work.m1.get("/me").json()["owns_projects"] is True
    opts = work.m1.get("/ai-reports/options").json()
    assert opts["all_projects"] is False and [p["name"] for p in opts["projects"]] == ["Apollo"]
    assert opts["ai_enabled"] is False


def test_owner_limited_to_owned_projects(work):
    make_owner(work, work.m1)
    bad = work.m1.post("/ai-reports", {**window(work), "project_ids": [work.hermes["id"]]})
    assert bad.status_code == 403
    rep = create(work.m1, work)  # defaults to the owned projects only
    assert rep["project_names"] == ["Apollo"]
    # nobody else can open it, the admin can
    assert work.m2.get(f"/ai-reports/{rep['id']}").status_code == 403
    make_owner(work, work.m2, work.hermes)
    assert work.m2.get(f"/ai-reports/{rep['id']}").status_code == 404
    assert work.admin.get(f"/ai-reports/{rep['id']}").status_code == 200
    assert [r["id"] for r in work.m1.get("/ai-reports").json()["items"]] == [rep["id"]]


def test_validation(work):
    assert work.admin.post("/ai-reports", {**window(work), "period_start": "2030-01-01"}).json()["code"] == "invalid_range"
    assert work.admin.post("/ai-reports", {**window(work), "format_mode": "sample", "format_sample": "x"}).json()["code"] == "sample_required"
    assert work.admin.post("/ai-reports", {**window(work), "project_ids": ["00000000-0000-0000-0000-000000000000"]}).json()["code"] == "invalid_project"
    assert work.admin.post("/ai-reports", {**window(work), "format_mode": "weird"}).status_code == 422


# ------------------------------------------------------------------ flow without an LLM
def test_standard_flow_without_llm(work):
    rep = create(work.admin, work)
    assert rep["status"] == "outline_ready" and rep["written_by"] == "builtin"
    titles = [s["title"] for s in rep["outline"]["sections"]]
    assert len(titles) >= 8 and rep["outline"]["per_project_count"] >= 1
    assert all({"id", "title", "scope", "visual", "what"} <= set(s) for s in rep["outline"]["sections"])
    assert work.admin.get(f"/ai-reports/{rep['id']}/preview").status_code == 409  # not written yet

    r = work.admin.post(f"/ai-reports/{rep['id']}/approve")
    assert r.status_code == 202 and r.json()["status"] == "generating"
    assert work.admin.post(f"/ai-reports/{rep['id']}/approve").status_code == 202  # double click
    drain()
    done = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert done["status"] == "ready", done
    assert work.admin.post(f"/ai-reports/{rep['id']}/approve").json()["status"] == "ready"
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown")
    import os
    if os.environ.get("DUMP_MD"):
        Path(os.environ["DUMP_MD"]).write_text(md.text)
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    text = md.text
    assert "Apollo" in text and "Hermes" in text
    assert "```mermaid" in text  # charts are rendered from code-computed numbers
    assert "<script" not in text.lower()
    html = work.admin.get(f"/ai-reports/{rep['id']}/preview").json()["html"]
    assert "<svg" in html and "Apollo" in html

    dl = done["downloads"]
    assert dl["md"] and dl["docx"] and dl["xlsx"]
    docx = work.admin.c.get(dl["docx"]).content
    assert zipfile.ZipFile(io.BytesIO(docx)).testzip() is None
    xlsx = work.admin.c.get(dl["xlsx"]).content
    assert xlsx[:2] == b"PK"
    if pdf_works():
        assert dl["pdf"] and work.admin.c.get(dl["pdf"]).content.startswith(b"%PDF")


def test_change_structure_and_rewrite(work):
    rep = create(work.admin, work)
    r = work.admin.post(f"/ai-reports/{rep['id']}/change-structure", {"note": "make it short"})
    assert r.status_code == 202
    assert work.admin.post(f"/ai-reports/{rep['id']}/change-structure", {"note": "x"}).status_code == 422
    drain()
    again = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert again["status"] == "outline_ready"
    assert work.admin.post(f"/ai-reports/{rep['id']}/rewrite", {"note": "shorter please"}).json()["code"] == "not_ready"
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    assert work.admin.post(f"/ai-reports/{rep['id']}/change-structure", {"note": "no way"}).json()["code"] == "not_changeable"
    assert work.admin.post(f"/ai-reports/{rep['id']}/rewrite", {"note": "shorter please"}).status_code == 202
    drain()
    assert work.admin.get(f"/ai-reports/{rep['id']}").json()["status"] == "ready"
    assert work.admin.post(f"/ai-reports/{rep['id']}/retry").json()["code"] == "not_failed"
    assert work.admin.delete(f"/ai-reports/{rep['id']}").status_code == 204
    assert work.admin.get(f"/ai-reports/{rep['id']}").status_code == 404


def test_visibility_mode_is_the_known_structure(work):
    rep = create(work.admin, work, format_mode="visibility")
    titles = [s["title"] for s in rep["outline"]["sections"]]
    assert 9 <= len(titles) <= 13
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    assert md.lstrip().startswith("#") and "\n---\n" in md


def test_sample_mode_reproduces_given_structure(work):
    rep = create(work.admin, work, format_mode="sample", format_sample=SAMPLE)
    sections = rep["outline"]["sections"]
    assert len(sections) >= 6
    # every project-level section appears once and is repeated per project at assembly
    assert any(s["scope"] == "per_project" for s in sections)
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    done = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert done["status"] == "ready"
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    for p in ("Apollo", "Hermes"):
        assert md.count(p) >= 2


def test_simple_sample_outline(work):
    sample = "Executive summary\nProjects table\nRisks\nNext steps\nBudget notes"
    rep = create(work.admin, work, format_mode="sample", format_sample=sample)
    titles = [s["title"].lower() for s in rep["outline"]["sections"]]
    assert len(titles) == 5 and titles[0].startswith("executive") and titles[-1].startswith("budget")


# ------------------------------------------------------------------ with a (fake) LLM
PLAN = {
    "title": "Leadership update", "heading_level": 2, "notes": "",
    "sections": [
        {"id": "a", "title": "Summary", "scope": "overall", "kind": "text", "brief": "two sentences", "style": "paragraph"},
        {"id": "b", "title": "Projects", "scope": "overall", "kind": "block", "block": "projects_table"},
        {"id": "c", "title": "Status of {project}", "scope": "per_project", "kind": "block", "block": "status_pie"},
        {"id": "d", "title": "Next steps", "scope": "overall", "kind": "text", "brief": "what's next", "style": "bullets"},
    ],
}


def test_llm_plans_and_writes_without_leaking_people(work, monkeypatch):
    calls: list = []
    fake_llm(monkeypatch, plan=PLAN, record=calls,
             write=lambda items: {i["key"]: ("Person A did well. <b>x</b>" if i["key"] == "a" else "- Ship it\n- Review risks") for i in items})
    rep = create(work.admin, work)
    assert rep["status"] == "outline_ready" and rep["written_by"] == "ai"
    assert rep["outline"]["sections"][0]["title"] == "Summary"
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    done = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert done["status"] == "ready" and done["written_by"] == "ai"
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    assert "<b>" not in md  # AI text is escaped
    assert "Ship it" in md
    assert len(calls) >= 2
    for system, user in calls:
        for name in ("Mia Member", "Max Member", "Olive Outsider", "Leo Lead", "Maya Manager", "Ada Admin"):
            assert name not in system and name not in user, name


def test_llm_missing_text_falls_back_and_is_flagged(work, monkeypatch):
    fake_llm(monkeypatch, plan=PLAN, write=lambda items: {items[0]["key"]: "Only this one"})
    rep = create(work.admin, work)
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    done = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert done["status"] == "ready" and done["missing_text"] is True


def test_llm_failure_falls_back_to_builtin(work, monkeypatch):
    fake_llm(monkeypatch, plan=RuntimeError("model down"))
    rep = create(work.admin, work)
    # retried by the queue; the final attempt uses the built-in outline instead of failing
    for _ in range(6):
        drain()
        rep = work.admin.get(f"/ai-reports/{rep['id']}").json()
        if rep["status"] != "planning":
            break
    assert rep["status"] == "outline_ready" and rep["written_by"] == "builtin"
    fake_llm(monkeypatch, plan=RuntimeError("model down"), write=RuntimeError("still down"))
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    for _ in range(6):
        drain()
        done = work.admin.get(f"/ai-reports/{rep['id']}").json()
        if done["status"] != "generating":
            break
    assert done["status"] == "ready"
    assert work.admin.get(f"/ai-reports/{rep['id']}/markdown").status_code == 200


# ------------------------------------------------------------------ units
def test_validate_outline_and_assemble(work):
    from app.services.airep import outline

    raw = {"title": "T", "sections": [
        {"title": "A", "scope": "overall", "kind": "block", "block": "no_such_block"},
        {"title": "B", "scope": "overall", "kind": "block", "block": "status_pie"},  # per-project block, overall scope -> coerced
        {"title": "C", "kind": "text", "brief": "x"},
    ] * 20}
    out = outline.validate_outline(raw)
    assert len(out["sections"]) <= 25
    assert [s["id"] for s in out["sections"][:3]] == ["s1", "s2", "s3"]
    assert all(s["kind"] in ("block", "text") for s in out["sections"])
    with pytest.raises(Exception):  # noqa: B017
        outline.validate_outline({"title": "x", "sections": []})
    assert isinstance(outline.describe(out), list)


def test_markdown_to_docx_handles_tables_and_charts():
    from app.services.airep.files import markdown_to_docx

    md = "# Title\n\nPara with **bold**.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n> quote\n\n- one\n- two\n\n```mermaid\npie title Work\n  \"Dev\" : 3\n  \"QA\" : 1\n```\n"
    data = markdown_to_docx(md)
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None


def test_plain_outline_per_project_and_lists(work):
    rep = create(work.admin, work, format_mode="sample", format_sample="1. Executive summary\n2. Progress per project\n3. Next steps")
    sections = rep["outline"]["sections"]
    assert [s["scope"] for s in sections] == ["overall", "per_project", "overall"]
    assert sections[1]["title"] == "Progress — {project}"
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    assert "Progress — Apollo" in md and "Progress — Hermes" in md
    assert "Needs attention:\n\n- " in md  # a list after a paragraph is separated so it renders as a list


def test_person_filter(work):
    opts = work.admin.get("/ai-reports/options").json()
    assert {"Mia Member", "Max Member"} <= {p["name"] for p in opts["people"]}
    rep = create(work.admin, work, person_ids=[work.m2.user_id])
    assert rep["people_names"] == ["Max Member"]
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    assert "work by Max Member" in md and "Ship login" not in md
    assert work.admin.post("/ai-reports", {**window(work), "person_ids": ["00000000-0000-0000-0000-000000000000"]}).json()["code"] == "invalid_person"


def test_owner_person_choices_limited_to_their_projects(work):
    make_owner(work, work.m1)  # Apollo; Mia/Max/Olive have Apollo tasks but only members count
    opts = work.m1.get("/ai-reports/options").json()
    assert all(p["name"] != "Ada Admin" for p in opts["people"])
    assert work.m1.post("/ai-reports", {**window(work), "person_ids": [work.admin.user_id]}).json()["code"] == "invalid_person"
