"""Nightly golden-set run against the REAL model: `pytest -m eval` with a provider key. Thresholds live in evals/thresholds.yaml."""

import json
import os
from pathlib import Path

import pytest

from app.services import ai
from evals import runner

from .conftest import drain
from .test_ai_reports import make_owner

pytestmark = pytest.mark.eval
LIVE = [c for c in runner.load_cases() if c["group"] in ("standard", "sample", "injection")]
RESULTS: list[runner.Result] = []


@pytest.fixture(autouse=True)
def real_key():
    from app.config import get_settings

    get_settings.cache_clear()
    if ai.resolve_config() is None:
        pytest.skip("no AI provider key in the environment")


QUESTIONS = runner.load_cases("question")


@pytest.mark.parametrize("case", QUESTIONS, ids=lambda c: c["id"])
def test_question(case, work):
    res = runner.run_question(case, work, runner.actors_for(work))
    RESULTS.append(res)
    assert not res.leak, res.problems  # a scope leak fails at once, whatever the thresholds say


@pytest.mark.parametrize("case", LIVE, ids=lambda c: c["id"])
def test_case(case, work, owner_conn):
    make_owner(work, work.m1)
    res = runner.run_case(case, work, drain, owner_conn, {"admin": work.admin, "owner": work.m1})
    RESULTS.append(res)


def test_thresholds():
    """Runs last: summarise every live case and compare with the gates; the report is written for the nightly job to upload."""
    summary = runner.summarise(RESULTS)
    out = Path(os.environ.get("EVAL_REPORT_DIR", "."))
    (out / "eval-report.json").write_text(json.dumps(summary, indent=1))
    assert not runner.breaches(summary), f"{runner.breaches(summary)} — failures: {summary['failures']}"
