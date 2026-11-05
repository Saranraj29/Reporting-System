# Runbook: mass remediation for AI writes (Phase 3)

Reserved for the Change capability (proposals that write to tasks). Not needed while the assistant is read-only. When Phase 3 ships: query `ai_proposals` by
time window, classify each applied row as unchanged / edited / deleted since apply, dry-run the inverse operations, get the report approved, apply in batches of
50 with optimistic locking, and notify the affected users.
