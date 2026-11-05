# Runbook: provider key rotation and secret handling

* Production keys live in the secret manager and reach the containers as environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`).
  They are never committed and never in `docker-compose.yml` in production (the compose file only passes `${VAR}` through for local runs).
* Rotate on a schedule (every 90 days) and **immediately** on suspicion of exposure: issue the new key, update the secret, restart API and workers, revoke the old key.
* Error text from providers is redacted of the key before it is logged or stored (`test_provider_http_errors_never_leak_the_key`).
* No key is shown anywhere in the UI or API.
