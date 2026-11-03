"""Delivering one notification: email, plus Slack when the company configured a webhook.
Each channel is attempted separately and written to notification_log; on partial failure only the
failed channels are retried (job-level retry, 3 attempts, then they stay `failed` in the log)."""

import logging

from sqlalchemy.orm import Session

from ..models import Company, Job, NotificationLog, User
from ..security import decrypt
from . import mail

log = logging.getLogger("notify")


class DeliveryError(Exception):
    pass


def deliver(db: Session, job: Job, company: Company, user: User | None, to_email: str | None, kind: str,
            subject: str, body: str, payload: dict | None = None) -> None:
    webhook = decrypt(company.slack_webhook_url)
    default_channels = (["email"] if to_email else []) + (["slack"] if webhook else [])
    pending: list[str] = list(job.payload.get("pending_channels", default_channels))
    failed: list[str] = []
    last_error = ""
    final = job.attempts >= job.max_attempts
    for channel in pending:
        try:
            if channel == "email" and to_email:
                mail.send_email(to_email, subject, body)
            elif channel == "slack" and webhook:
                mail.post_slack(webhook, f"*{subject}*\n{body}")
            db.add(NotificationLog(company_id=company.id, user_id=user.id if user else None, kind=kind,
                                   channel=channel, status="sent", payload=payload or {"subject": subject}))
        except Exception as exc:  # noqa: BLE001 - any provider error is retried
            log.warning("notification %s via %s failed: %s", kind, channel, exc)
            failed.append(channel)
            last_error = str(exc)[:500]
            if final:
                db.add(NotificationLog(company_id=company.id, user_id=user.id if user else None, kind=kind,
                                       channel=channel, status="failed", error=last_error,
                                       payload=payload or {"subject": subject}))
    db.commit()  # keep the log rows for channels that already succeeded
    if failed:
        job.payload = {**job.payload, "pending_channels": failed}
        raise DeliveryError(f"{kind}: {', '.join(failed)} failed: {last_error}")
