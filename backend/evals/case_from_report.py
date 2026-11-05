"""`python -m evals.case_from_report <ai_report_id>` — copies a down-voted report's request into evals/cases/feedback.json (request text, mode, period length,
sample). Names and facts are NOT copied: the case runs against the evaluation company. Review the file before committing."""

import json
import sys
from pathlib import Path

from sqlalchemy import select, text

from app.db import new_session
from app.models import AiReport

FILE = Path(__file__).parent / "cases" / "feedback.json"


def main(report_id: str) -> None:
    db = new_session()
    try:
        db.execute(text("SELECT set_config('app.company_id', (SELECT company_id::text FROM ai_reports WHERE id = :i), false)"), {"i": report_id})
        row = db.execute(select(AiReport).where(AiReport.id == report_id)).scalar_one()
        case = {
            "id": f"feedback-{str(row.id)[:8]}", "group": "standard" if row.format_mode != "sample" else "sample", "request": row.request, "mode": row.format_mode,
            "sample": row.format_sample, "headings": [], "period_days": max((row.period_end - row.period_start).days, 1), "as": "admin", "from_feedback": True,
        }
    finally:
        db.close()
    cases = json.loads(FILE.read_text()) if FILE.exists() else []
    cases.append(case)
    FILE.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n")
    print("added", case["id"])


if __name__ == "__main__":
    main(sys.argv[1])
