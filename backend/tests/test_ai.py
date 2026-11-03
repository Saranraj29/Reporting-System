import pytest

from app.services import ai


def test_sanitize_strips_personal_and_internal_keys_recursively():
    f = {"totals": {"hours": 3}, "people": [{"name": "Mia"}], "projects": [{"project": "A", "comments": ["x"], "hours": 1}],
         "daily_status": {"blockers": ["secret"]}}
    out = ai.sanitize_figures(f)
    assert out == {"totals": {"hours": 3}, "projects": [{"project": "A", "hours": 1}]}


def test_parse_model_output_extracts_json_and_flags_gaps():
    out = ai.parse_model_output('noise {"sections": {"A": " one "}, "questions": ["q?"]} trailing', ["A", "B"])
    assert out["A"] == "one" and out["B"] == ""
    assert out["_questions"][0] == "q?" and "B" in out["_questions"][1]
    with pytest.raises(ValueError):
        ai.parse_model_output("no json here", ["A"])
    with pytest.raises(ValueError):
        ai.parse_model_output('{"sections": []}', ["A"])


def test_figures_only_text_uses_only_given_numbers():
    figs = {"period": {"start": "2026-01-05", "end": "2026-01-11"}, "totals": {"hours": 12.5, "tasks_completed": 3, "tasks_open": 4},
            "projects": [{"project": "Apollo", "hours": 12.5}], "completed_tasks": [{"title": "T", "project": "Apollo"}],
            "blockers": [], "overdue": [], "upcoming": []}
    out = ai.figures_only_text(figs, ["Summary", "Hours by area", "Risks and blockers", "Custom"])
    assert "12.5 hours" in out["Summary"] and "- Apollo: 12.5 h" == out["Hours by area"]
    assert out["Risks and blockers"] == "No blockers or overdue work."
    assert out["Custom"] == "" and "Custom" in out["_questions"][0]  # never invents content: asks instead


def test_draft_without_key_never_calls_the_model(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(ai, "_call_model", lambda *a: pytest.fail("model must not be called"))
    text, provider = ai.draft_report_text({"totals": {}}, {"sections": ["Summary"]})
    assert provider == "figures_only" and "Summary" in text
