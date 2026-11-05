# Runbook: wrong AI output at scale (a bad prompt or model version)

1. **Stop it.** Company switch (Settings → "AI-written text" off) for one company, or `AI_ENABLED=false` for everyone. Effective within 60 s.
2. **Find what is affected.** `ai_calls` has `prompt_version`, `model` and `created_at` for every call; `ai_reports` carries the same on each report:
   `select id, company_id, created_by from ai_reports where prompt_version = 'write_v2' and created_at > '<start>';`
3. **Regenerate** the affected reports with the built-in wording. Facts are stored on the report, so this is cheap and deterministic: enqueue
   `ai_report.generate` for each id after setting the company switch off (or `AI_ENABLED=false`), so the job takes the built-in path.
4. **Tell the requesters** (the `created_by` users) which reports changed and why.
5. **Block the prompt version.** Revert the prompt file (or fix it as a new version), run `pytest -m eval`, then `python -m evals.stamp` and commit the stamp.
   Only then switch AI back on.
