"""The transactional e-mails: one subject, a plain-text body and an HTML body per kind, all in the same simple layout. Every value that came from a
person (names, company) is HTML-escaped. Links are built by the caller; nothing here knows how to mint a token."""

from datetime import datetime
from html import escape

PRODUCT = "Project Transparency"


def _layout(title: str, intro: str, button: tuple[str, str] | None, outro: str, footer: str) -> str:
    btn = (
        f'<p style="margin:28px 0"><a href="{escape(button[1], quote=True)}" style="background:#3b5bdb;color:#ffffff;text-decoration:none;'
        f'padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block">{escape(button[0])}</a></p>'
        f'<p style="font-size:13px;color:#667085">Button not working? Copy this link into your browser:<br>'
        f'<a href="{escape(button[1], quote=True)}" style="color:#3b5bdb;word-break:break-all">{escape(button[1])}</a></p>'
        if button else ""
    )
    return (
        '<!doctype html><html><body style="margin:0;background:#f4f6fb;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;'
        'border:1px solid #e4e8f0"><tr><td style="padding:32px">'
        f'<p style="margin:0 0 20px;font-size:13px;font-weight:700;letter-spacing:.04em;color:#3b5bdb;text-transform:uppercase">{PRODUCT}</p>'
        f'<h1 style="margin:0 0 16px;font-size:22px;color:#101828">{escape(title)}</h1>'
        f'<p style="margin:0;font-size:15px;line-height:1.6;color:#344054">{intro}</p>{btn}'
        f'<p style="margin:0;font-size:14px;line-height:1.6;color:#475467">{outro}</p>'
        '</td></tr></table>'
        f'<p style="max-width:560px;font-size:12px;line-height:1.5;color:#98a2b3;margin:16px 0 0">{footer}</p>'
        '</td></tr></table></body></html>'
    )


def _text(title: str, intro: str, link: str | None, outro: str, footer: str) -> str:
    parts = [title, "", intro, ""]
    if link:
        parts += [link, ""]
    return "\n".join(parts + [outro, "", "--", f"{PRODUCT} · {footer}", ""])


def verify_email(name: str, link: str) -> tuple[str, str, str]:
    title, intro = "Confirm your email address", f"Hi {name}, welcome! Please confirm that this is your email address so you can sign in."
    outro = "This link works for 48 hours. If you did not create an account, you can ignore this email."
    footer = "You received this because someone registered with this address."
    return title, _text(title, intro, link, outro, footer), _layout(title, escape(intro), ("Confirm email address", link), escape(outro), escape(footer))


def password_reset(name: str, link: str) -> tuple[str, str, str]:
    title, intro = "Reset your password", f"Hi {name}, we received a request to reset your password. The link below works once, for one hour."
    outro = "If you did not ask for this, ignore this email: your password stays the same."
    footer = "You received this because a password reset was requested for your account."
    return title, _text(title, intro, link, outro, footer), _layout(title, escape(intro), ("Choose a new password", link), escape(outro), escape(footer))


def invite(inviter: str, company: str, link: str) -> tuple[str, str, str]:
    title = f"{inviter} invited you to {company}"
    intro = f"{inviter} invited you to join {company} on {PRODUCT}, where the team tracks tasks, time and project progress."
    outro = "Create your account with the button above. The invitation is valid for 7 days; if you were not expecting it, you can ignore this email."
    footer = f"You received this because {inviter} entered your email address."
    return title, _text(title, intro, link, outro, footer), _layout(title, escape(intro), ("Accept invitation", link), escape(outro), escape(footer))


def password_changed(name: str, when: datetime, tz_name: str, forgot_link: str, how: str) -> tuple[str, str, str]:
    """`how`: 'changed' (from the profile page) or 'reset' (through a reset link)."""
    title = "Your password was changed"
    stamp = when.strftime("%d %b %Y, %H:%M") + f" ({tz_name})"
    intro = f"Hi {name}, the password of your account was {'reset' if how == 'reset' else 'changed'} on {stamp}. Other devices were signed out."
    outro = "If this was you, there is nothing to do. If it was not, reset your password right away and tell your administrator."
    footer = "This is a security notice; you receive it whenever your password changes."
    return (title, _text(title, intro, forgot_link, outro, footer), _layout(title, escape(intro), ("Secure my account", forgot_link), escape(outro), escape(footer)))


def test_email(sender: str) -> tuple[str, str, str]:
    title, intro = "Test email", f"This is a test message sent by {sender}. If you can read this, email delivery from {PRODUCT} works."
    outro, footer = "Nothing else to do.", "Sent from Settings → Email delivery."
    return title, _text(title, intro, None, outro, footer), _layout(title, escape(intro), None, escape(outro), escape(footer))
