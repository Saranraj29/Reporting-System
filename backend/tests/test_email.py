"""Transactional e-mail: verify, reset, invite and 'password changed' go through the queue, with HTML + text, escaped, retried, logged; SMTP wiring and diagnostics."""

import re
import smtplib
import ssl

import pytest

from app.config import get_settings
from app.services import mail

from .conftest import PASSWORD, drain, login, signup_admin


def smtp_env(monkeypatch, **kv):
    base = dict(EMAIL_BACKEND="smtp", SMTP_HOST="smtp.example.test", SMTP_PORT="587", SMTP_USER="mailer", SMTP_PASSWORD="s3cret-pw", SMTP_SECURITY="starttls",
                EMAIL_FROM="Project Transparency <noreply@acme.test>", EMAIL_REPLY_TO="support@acme.test")
    for k, v in {**base, **kv}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def link_in(text: str, path: str) -> str:
    return re.search(rf"http\S*{re.escape(path)}\?\S+", text).group(0)


def mails(to: str | None = None) -> list[dict]:
    return [m for m in mail.outbox if to is None or m["to"] == to]


# ------------------------------------------------------------------ the four e-mails
def test_registration_sends_a_verification_email_with_a_working_link(client):
    r = client.post("/api/v1/auth/register", json={"email": "newbie@zeta.io", "password": PASSWORD, "name": "Nia <b>Newbie</b>", "company_name": "Zeta"})
    assert r.status_code == 201
    assert not mails("newbie@zeta.io")  # queued, not sent inside the request
    drain()
    m = mails("newbie@zeta.io")[0]
    assert m["subject"] == "Confirm your email address" and m["html"] and "Confirm email address" in m["html"]
    assert "Nia <b>Newbie</b>" not in m["html"] and "Nia &lt;b&gt;Newbie&lt;/b&gt;" in m["html"]  # names are escaped in the HTML part
    link = link_in(m["text"], "/verify-email")
    token = link.split("token=")[1]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert login(client, "newbie@zeta.io")


def test_no_token_or_link_is_stored_in_the_job_table(client, owner_conn):
    client.post("/api/v1/auth/register", json={"email": "a@zeta.io", "password": PASSWORD, "name": "A", "company_name": "Zeta"})
    client.post("/api/v1/auth/forgot-password", json={"email": "a@zeta.io"})
    payloads = [str(r[0]) for r in owner_conn.execute("select payload from jobs where kind = 'email.send'").fetchall()]
    assert len(payloads) == 2 and not any("eyJ" in p or "token" in p or "http" in p for p in payloads)  # ids only; the worker mints the link


def test_forgot_password_email_and_the_password_changed_notice(org, client):
    org.admin.post("/me/password", {"current_password": PASSWORD, "new_password": "Another-Passw0rd!"}).raise_for_status()
    drain()
    notice = next(m for m in mails("admin@acme.com") if m["subject"] == "Your password was changed")
    assert "was changed on" in notice["text"] and "Other devices were signed out" in notice["text"] and "/forgot-password" in notice["text"]
    assert "Secure my account" in notice["html"]
    mail.outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": "admin@acme.com"})
    drain()
    reset = mails("admin@acme.com")[0]
    assert reset["subject"] == "Reset your password" and "one hour" in reset["text"]
    token = link_in(reset["text"], "/reset-password").split("token=")[1]
    mail.outbox.clear()
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "Third-Passw0rd!x"}).status_code == 200
    drain()
    assert [m["subject"] for m in mails("admin@acme.com")] == ["Your password was changed"] and "was reset on" in mails("admin@acme.com")[0]["text"]
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "Fourth-Passw0rd!"}).status_code == 400  # a link works once
    mail.outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": "nobody@acme.com"})
    drain()
    assert not mail.outbox  # an unknown address gets nothing (and the API answered the same)


def test_invite_email_has_a_link_that_joins_the_company(org, client):
    org.admin.patch("/me/profile", {"name": "Ada <script>x</script>"}).raise_for_status()
    assert org.admin.post("/users/invite", {"email": "second@acme.com"}).status_code == 201
    assert not mails("second@acme.com")
    drain()
    m = mails("second@acme.com")[0]
    assert "invited you to Acme Corp" in m["subject"] and "<script>" not in m["html"] and "&lt;script&gt;" in m["html"]
    assert "Accept invitation" in m["html"] and "valid for 7 days" in m["text"]
    token = link_in(m["text"], "/register").split("invite=")[1]
    r = client.post("/api/v1/auth/register", json={"email": "second@acme.com", "password": PASSWORD, "name": "Sam Second", "invite_token": token})
    assert r.status_code == 201, r.text
    assert r.json()["verification_required"] is False  # the invitation itself proves the address
    assert [x["name"] for x in login(client, "second@acme.com").get("/me").json()["roles"]] == ["Team Member"]  # an invitee gets the minimum role


def test_resend_verification(client, owner_conn):
    client.post("/api/v1/auth/register", json={"email": "late@zeta.io", "password": PASSWORD, "name": "Late", "company_name": "Zeta"})
    drain()
    mail.outbox.clear()
    r = client.post("/api/v1/auth/resend-verification", json={"email": "late@zeta.io"})
    assert r.status_code == 200 and "dev_verification_token" in r.json()
    drain()
    assert [m["subject"] for m in mails("late@zeta.io")] == ["Confirm your email address"]
    mail.outbox.clear()
    other = client.post("/api/v1/auth/resend-verification", json={"email": "unknown@zeta.io"})
    drain()
    assert other.json()["message"] == r.json()["message"] and not mail.outbox  # same answer, no information
    owner_conn.execute("update users set email_verified_at = now() where email = 'late@zeta.io'")
    client.post("/api/v1/auth/resend-verification", json={"email": "late@zeta.io"})
    drain()
    assert not mail.outbox  # already verified: nothing to send


def test_verification_is_skipped_if_the_account_got_verified_meanwhile(client, owner_conn):
    client.post("/api/v1/auth/register", json={"email": "quick@zeta.io", "password": PASSWORD, "name": "Quick", "company_name": "Zeta"})
    owner_conn.execute("update users set email_verified_at = now() where email = 'quick@zeta.io'")
    drain()
    assert not mails("quick@zeta.io")


# ------------------------------------------------------------------ failures: retried, logged, readable
def test_a_failing_mail_server_is_retried_then_logged_without_leaking_the_password(client, monkeypatch, owner_conn):
    smtp_env(monkeypatch)

    def boom(s):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted for s3cret-pw")

    monkeypatch.setattr(mail, "_open_smtp", boom)
    client.post("/api/v1/auth/register", json={"email": "x@zeta.io", "password": PASSWORD, "name": "X", "company_name": "Zeta"})
    for _ in range(8):
        drain()
    job = owner_conn.execute("select status, attempts, last_error from jobs where kind = 'email.send'").fetchone()
    assert job[0] == "failed" and job[1] == 5  # five attempts, then it stops
    assert "rejected the username or password" in job[2] and "s3cret-pw" not in job[2]
    row = owner_conn.execute("select kind, status, error from notification_log where kind = 'email.verify_email'").fetchone()
    assert row[1] == "failed" and "rejected the username or password" in row[2] and "s3cret-pw" not in row[2]


def test_a_flaky_server_succeeds_on_a_retry(client, monkeypatch, owner_conn):
    smtp_env(monkeypatch)
    sent = []
    calls = {"n": 0}

    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            sent.append(msg)

    monkeypatch.setattr(mail, "_open_smtp", lambda s: Fake())
    client.post("/api/v1/auth/register", json={"email": "y@zeta.io", "password": PASSWORD, "name": "Y", "company_name": "Zeta"})
    for _ in range(3):
        drain()
    assert len(sent) == 1 and owner_conn.execute("select status from notification_log where kind = 'email.verify_email'").fetchone()[0] == "sent"
    assert "y@zeta.io" not in str(owner_conn.execute("select payload from notification_log").fetchall())  # only a masked address is logged


# ------------------------------------------------------------------ the SMTP wire format
class FakeSMTP:
    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.args, self.calls, self.sent = (host, port, timeout), [], []
        self.esmtp_features = {"auth": "LOGIN PLAIN XOAUTH2"}
        FakeSMTP.instances.append(self)

    def ehlo_or_helo_if_needed(self):
        self.calls.append("ehlo?")

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        assert isinstance(context, ssl.SSLContext)
        self.calls.append("starttls")

    def login(self, user, pw):
        self.calls.append(("login", user, pw))

    def send_message(self, msg):
        self.sent.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("security,port,cls,expects_starttls", [("starttls", "587", "SMTP", True), ("ssl", "465", "SMTP_SSL", False), ("none", "25", "SMTP", False)])
def test_smtp_connection_modes(monkeypatch, security, port, cls, expects_starttls):
    FakeSMTP.instances.clear()
    smtp_env(monkeypatch, SMTP_SECURITY=security, SMTP_PORT=port)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", type("FakeSSL", (FakeSMTP,), {}))
    mail.send_email("to@x.test", "Hello", "plain", "<p>html</p>")
    smtp = FakeSMTP.instances[0]
    assert type(smtp).__name__ == ("FakeSSL" if cls == "SMTP_SSL" else "FakeSMTP") and smtp.args == ("smtp.example.test", int(port), 20)
    assert ("starttls" in smtp.calls) is expects_starttls and ("login", "mailer", "s3cret-pw") in smtp.calls
    msg = smtp.sent[0]
    assert msg["From"] == "Project Transparency <noreply@acme.test>" and msg["Reply-To"] == "support@acme.test" and msg["To"] == "to@x.test"
    assert msg["Auto-Submitted"] == "auto-generated" and msg["Message-ID"].endswith("@acme.test>") and msg["Date"]
    assert msg.get_body(("plain",)).get_content().strip() == "plain" and msg.get_body(("html",)).get_content().strip() == "<p>html</p>"  # both parts


def test_config_problems_are_explained(monkeypatch):
    assert mail.config_problems() == []  # console in development
    smtp_env(monkeypatch, SMTP_HOST="localhost", SMTP_USER="", SMTP_PASSWORD="", EMAIL_FROM="Pt <no-reply@example.com>")
    text = " ".join(mail.config_problems())
    assert "SMTP_HOST" in text and "SMTP_USER" in text and "example.com" in text
    smtp_env(monkeypatch, SMTP_PORT="465")
    assert "Port 465 expects SMTP_SECURITY=ssl" in " ".join(mail.config_problems())
    smtp_env(monkeypatch, SMTP_SECURITY="none")
    assert "unencrypted" in " ".join(mail.config_problems())
    smtp_env(monkeypatch)
    assert mail.config_problems() == []


@pytest.mark.parametrize("exc,words", [
    (smtplib.SMTPAuthenticationError(535, b"bad"), "rejected the username or password"), (ConnectionRefusedError("refused"), "Could not reach the mail server"),
    (TimeoutError("t"), "did not answer"), (ssl.SSLError("tls"), "Secure connection"), (smtplib.SMTPSenderRefused(550, b"no", "a@b"), "refused the sender"),
])
def test_failures_have_readable_reasons(monkeypatch, exc, words):
    smtp_env(monkeypatch)
    monkeypatch.setattr(mail, "_open_smtp", lambda s: (_ for _ in ()).throw(exc))
    with pytest.raises(mail.MailError) as e:
        mail.send_email("to@x.test", "s", "t")
    assert words in str(e.value) and "s3cret-pw" not in str(e.value)


# ------------------------------------------------------------------ settings: test e-mail
def test_settings_show_the_mail_setup_without_the_password(org, monkeypatch):
    smtp_env(monkeypatch)
    out = org.admin.get("/settings").json()
    assert out["email"]["backend"] == "smtp" and out["email"]["host"] == "smtp.example.test" and out["email"]["security"] == "starttls"
    assert "s3cret-pw" not in str(out) and org.m1.get("/settings").json().get("email") is None  # only admins see how mail is set up


def test_test_email_button(org, monkeypatch):
    r = org.admin.post("/settings/test-email").json()
    assert r["ok"] and r["delivered"] is False and "Development mode" in r["message"]  # console backend: honest about it
    assert mails("admin@acme.com")[-1]["subject"] == "Test email"
    smtp_env(monkeypatch)
    sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(FakeSMTP, "send_message", lambda self, msg: sent.append(msg))
    r = org.admin.post("/settings/test-email").json()
    assert r["delivered"] is True and "admin@acme.com" in r["message"] and sent[0]["To"] == "admin@acme.com"
    monkeypatch.setattr(mail, "_open_smtp", lambda s: (_ for _ in ()).throw(smtplib.SMTPAuthenticationError(535, b"no")))
    bad = org.admin.post("/settings/test-email")
    assert bad.status_code == 502 and bad.json()["code"] == "email_failed" and "rejected the username or password" in bad.json()["message"]
    assert org.m1.post("/settings/test-email").status_code == 403


def test_mailcheck_command(monkeypatch, capsys):
    from app import mailcheck

    assert mailcheck.main([]) == 2 and mailcheck.main(["a@b.test"]) == 0
    smtp_env(monkeypatch)
    monkeypatch.setattr(mail, "_open_smtp", lambda s: (_ for _ in ()).throw(TimeoutError("t")))
    assert mailcheck.main(["a@b.test"]) == 1 and "did not answer" in capsys.readouterr().out


# ------------------------------------------------------------------ the development shortcuts disappear once real mail is on
def test_links_are_never_in_the_response_when_real_mail_is_on(client, monkeypatch):
    r = client.post("/api/v1/auth/register", json={"email": "p@zeta.io", "password": PASSWORD, "name": "P", "company_name": "Zeta"})
    assert "dev_verification_token" in r.json()  # console backend (development): the shortcut exists
    admin = signup_admin(client, domain="acme.com")  # (needs the shortcut to verify itself, so before real mail is switched on)
    smtp_env(monkeypatch)
    r = client.post("/api/v1/auth/register", json={"email": "q@zeta.io", "password": PASSWORD, "name": "Q", "company_name": "Zeta"})
    assert r.status_code == 201 and "dev_verification_token" not in r.json()  # real mail: the link only travels by email
    assert "dev_reset_token" not in client.post("/api/v1/auth/forgot-password", json={"email": "q@zeta.io"}).json()
    assert "dev_verification_token" not in client.post("/api/v1/auth/resend-verification", json={"email": "q@zeta.io"}).json()
    assert "dev_invite_link" not in admin.post("/users/invite", {"email": "new@acme.com"}).json()


def test_a_dropped_connection_says_where_it_dropped(monkeypatch):
    smtp_env(monkeypatch)

    class DropsAtTls(FakeSMTP):
        def starttls(self, context=None):
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(smtplib, "SMTP", DropsAtTls)
    with pytest.raises(mail.MailError) as e:
        mail.send_email("to@x.test", "s", "t")
    msg = str(e.value)
    assert "closed the connection while starting TLS (STARTTLS)" in msg and "SMTP_PORT=465" in msg and "firewall" in msg and "s3cret-pw" not in msg


def test_ipv4_addresses_are_tried_before_ipv6(monkeypatch):
    """Docker Desktop's IPv6 accepts a connection and then drops it; the sender must reach for IPv4 first."""
    import socket

    tried = []

    class FakeSock:
        def __init__(self, family, *a):
            self.family = family

        def settimeout(self, t):
            pass

        def connect(self, addr):
            tried.append(addr[0])

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, type=0: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2404:6800::6d", port, 0, 0)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("74.125.0.1", port))])
    monkeypatch.setattr(socket, "socket", FakeSock)
    assert mail._connect_v4_first("smtp.example.test", 587, 5).family == socket.AF_INET
    assert tried == ["74.125.0.1"]  # IPv6 was never needed
    tried.clear()
    monkeypatch.setattr(FakeSock, "connect", lambda self, addr: (_ for _ in ()).throw(OSError("no route")) if self.family == socket.AF_INET else tried.append(addr[0]))
    assert mail._connect_v4_first("smtp.example.test", 587, 5).family == socket.AF_INET6  # IPv6 is still the fallback when IPv4 does not connect
    assert mail._v4_first(smtplib.SMTP).__name__ == "SMTP" and mail._v4_first(smtplib.SMTP_SSL).__name__ == "SMTP_SSL"


def test_debug_output_never_contains_credentials():
    assert mail.redact_debug("send: 'AUTH PLAIN AHVzZXIAcGFzcw=='") == "send: 'AUTH PLAIN ***'"
    assert mail.redact_debug("send: 'c2VjcmV0LXB3\\r\\n'") == "send: '***\\r\\n'"
    assert mail.redact_debug("reply: b'334 UGFzc3dvcmQ6'") == "reply: b'334 ***'"
    assert mail.redact_debug("reply: b'250-AUTH LOGIN PLAIN XOAUTH2'") == "reply: b'250-AUTH LOGIN PLAIN XOAUTH2'"  # the server's menu is kept
    from app import mailcheck

    assert mailcheck.main(["--debug"]) == 2


def test_a_rejected_password_is_reported_as_such_not_as_a_dropped_connection(monkeypatch):
    """Gmail hangs up on the LOGIN retry that smtplib does after a rejected PLAIN: only PLAIN may be tried, so the 535 reaches the user."""
    FakeSMTP.instances.clear()
    smtp_env(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    mail.send_email("to@x.test", "s", "t")
    assert FakeSMTP.instances[0].esmtp_features["auth"] == "PLAIN"

    class Rejects(FakeSMTP):
        def login(self, user, pw):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted. BadCredentials")

    monkeypatch.setattr(smtplib, "SMTP", Rejects)
    with pytest.raises(mail.MailError) as e:
        mail.send_email("to@x.test", "s", "t")
    assert "rejected the username or password" in str(e.value) and "BadCredentials" in str(e.value) and "firewall" not in str(e.value)
