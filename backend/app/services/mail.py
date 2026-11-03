import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger("mail")
outbox: list[dict] = []  # console backend keeps what it "sent" (dev and tests)


def send_email(
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    s = get_settings()
    if s.email_backend == "console":
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, text)
        outbox.append({"to": to, "subject": subject, "text": text, "attachments": [a[0] for a in attachments or []]})
        del outbox[:-200]
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.email_from, to, subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)


def post_slack(webhook_url: str, text: str) -> None:
    import httpx

    r = httpx.post(webhook_url, json={"text": text}, timeout=10)
    r.raise_for_status()
