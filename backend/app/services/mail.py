"""Outgoing e-mail. Two backends: `console` (development: the mail is written to the log and kept in `outbox`) and `smtp` (real delivery over
STARTTLS or implicit TLS). Transactional mail (verify, reset, invite, password changed) goes through the `email.send` job, so a slow or failing
mail server never blocks a request and a failed send is retried; this module only does the sending."""

import logging
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from ..config import get_settings

log = logging.getLogger("mail")
outbox: list[dict] = []  # console backend keeps what it "sent" (dev and tests)


class MailError(Exception):
    """A delivery problem with a message that is safe to show an admin (never contains the password)."""


def _from_header(s) -> tuple[str, str]:
    name, addr = parseaddr(s.email_from)
    return name or "Project Transparency", addr


def config_problems() -> list[str]:
    """What is wrong with the mail settings, in words an admin can act on. Empty = fine."""
    s = get_settings()
    out: list[str] = []
    _, addr = _from_header(s)
    if s.email_backend == "console":
        if s.is_prod:
            out.append("EMAIL_BACKEND is 'console': emails are only written to the server log. Set EMAIL_BACKEND=smtp to really send them.")
        return out
    if s.email_backend != "smtp":
        return [f"EMAIL_BACKEND '{s.email_backend}' is not known (use 'console' or 'smtp')."]
    if s.smtp_host in ("", "localhost", "127.0.0.1"):
        out.append("SMTP_HOST is not set to your mail provider.")
    if not s.smtp_user or not s.smtp_password:
        out.append("SMTP_USER / SMTP_PASSWORD are not both set; most providers reject mail without them.")
    if s.smtp_security not in ("starttls", "ssl", "none"):
        out.append("SMTP_SECURITY must be starttls, ssl or none.")
    elif s.smtp_security == "none" and s.smtp_host not in ("localhost", "127.0.0.1"):
        out.append("SMTP_SECURITY=none sends your password and mail unencrypted; use starttls (587) or ssl (465).")
    if s.smtp_security == "starttls" and s.smtp_port == 465:
        out.append("Port 465 expects SMTP_SECURITY=ssl, not starttls.")
    if s.smtp_security == "ssl" and s.smtp_port == 587:
        out.append("Port 587 expects SMTP_SECURITY=starttls, not ssl.")
    if not addr or addr.endswith("@example.com"):
        out.append("EMAIL_FROM still uses the example.com address; use an address your provider allows you to send from.")
    return out


def _open_smtp(s) -> smtplib.SMTP:
    """Opens the connection. If a step fails, the exception carries which step (`_mail_stage`), so 'connection closed' can say WHERE it closed."""
    stage = "connecting to the server"
    try:
        ctx = ssl.create_default_context()
        if s.smtp_security == "ssl":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout, context=ctx)
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout)
            stage = "saying hello (EHLO)"
            smtp.ehlo()
            if s.smtp_security == "starttls":
                stage = "starting TLS (STARTTLS)"
                smtp.starttls(context=ctx)
                stage = "saying hello again after TLS"
                smtp.ehlo()
        if s.smtp_user:
            stage = "logging in"
            smtp.login(s.smtp_user, s.smtp_password or "")
        return smtp
    except Exception as exc:
        exc._mail_stage = stage  # type: ignore[attr-defined]
        raise


def _friendly(exc: Exception, s) -> MailError:
    """A readable reason; the raw server text is cut short and the password is blanked out."""
    raw = re.sub(re.escape(s.smtp_password), "***", str(exc)) if s.smtp_password else str(exc)
    raw = raw[:200]
    where = f"{s.smtp_host}:{s.smtp_port}"
    stage = getattr(exc, "_mail_stage", "sending the message")
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return MailError(
            f"The mail server {where} closed the connection while {stage}. This is usually a firewall, VPN or antivirus on your network blocking or "
            f"inspecting outgoing mail on port {s.smtp_port}. Try SMTP_PORT=465 with SMTP_SECURITY=ssl (or 587 with starttls), another network, or ask "
            f"your provider. ({raw})"
        )
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return MailError(f"The mail server {where} rejected the username or password. (Gmail needs an App Password.) Server said: {raw}")
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionRefusedError, socket.gaierror)):
        return MailError(f"Could not reach the mail server {where}. Check SMTP_HOST and SMTP_PORT and that the network allows it. ({raw})")
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return MailError(f"The mail server {where} did not answer within {s.smtp_timeout} s.")
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return MailError(f"Secure connection to {where} failed; check SMTP_SECURITY (starttls for 587, ssl for 465). ({raw})")
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return MailError(f"The mail server refused the sender address. Set EMAIL_FROM to an address your account may send from. ({raw})")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return MailError(f"The mail server refused the recipient address. ({raw})")
    return MailError(f"Sending failed: {type(exc).__name__}: {raw}")


def send_email(
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> str | None:
    """Sends one message (text, plus an HTML alternative when given). Returns the Message-ID. Raises MailError when the server says no."""
    s = get_settings()
    if s.email_backend == "console":
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, text)
        outbox.append({"to": to, "subject": subject, "text": text, "html": html, "attachments": [a[0] for a in attachments or []]})
        del outbox[:-200]
        return None
    name, addr = _from_header(s)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = formataddr((name, addr)), to, subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] or None)
    if s.email_reply_to:
        msg["Reply-To"] = s.email_reply_to
    msg["Auto-Submitted"] = "auto-generated"  # machine-sent: keeps out-of-office replies from looping back
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for fname, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    try:
        with _open_smtp(s) as smtp:
            try:
                smtp.send_message(msg)
            except Exception as exc:
                exc._mail_stage = "sending the message"  # type: ignore[attr-defined]
                raise
    except Exception as exc:  # noqa: BLE001
        raise _friendly(exc, s) from exc
    log.info("EMAIL sent to=%s subject=%s id=%s", mask(to), subject, msg["Message-ID"])
    return msg["Message-ID"]


def mask(address: str) -> str:
    """j***@example.com — enough to recognise a recipient in the logs without storing the address."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def queue_email(db, company_id, kind: str, **payload) -> None:
    """Hands a transactional e-mail to the worker (`email.send`): 5 attempts with growing back-off. The payload names WHAT to send (kind + ids), never a
    token or link: those are minted by the worker at send time, so no secret is stored in the job table."""
    from . import jobs

    jobs.enqueue(db, "email.send", company_id, {"kind": kind, **payload}, max_attempts=5)


def post_slack(webhook_url: str, text: str) -> None:
    import httpx

    r = httpx.post(webhook_url, json={"text": text}, timeout=10)
    r.raise_for_status()
