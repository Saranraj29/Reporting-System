# Weekly feedback triage

Owner: the **AI product owner** (named by the project lead before the pilot).

Every Monday:
1. Open Settings → AI usage this month: note the thumbs-down count. Alert if it doubled week over week.
2. List the down-votes with a reason: `select target_id, reason, created_at from ai_feedback where rating = -1 and created_at > now() - interval '7 days';`
3. For each one decide: **harness failure** (information missing, wrong data, a verifier miss) or **model failure** (all information present, wrong reasoning), or **not a defect** (taste).
4. For a real defect turn the report into an eval case: `python -m evals.case_from_report <ai_report_id>` appends it to `evals/cases/feedback.json`.
   Review the case file in the PR (no names or private text), then run the golden set.
5. Upgrade the model only when model failures dominate; fix the harness otherwise.
