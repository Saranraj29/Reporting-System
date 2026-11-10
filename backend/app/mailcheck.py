"""`python -m app.mailcheck you@example.com` — checks the mail settings and sends one test message. Run it inside the container:
docker compose exec api python -m app.mailcheck you@example.com"""

import sys

from .config import get_settings
from .services import mail, mail_templates


def main(argv: list[str]) -> int:
    debug = "--debug" in argv
    argv = [a for a in argv if a != "--debug"]
    if len(argv) != 1 or "@" not in argv[0]:
        print("usage: python -m app.mailcheck [--debug] <your email address>")
        return 2
    mail.DEBUG = debug  # --debug: print the conversation with the mail server (credentials blanked)
    s = get_settings()
    who = mail.mask(s.smtp_user) if s.smtp_user else "NOT set"
    pw = f"{len(s.smtp_password)} characters" if s.smtp_password else "NOT set"
    print(f"backend={s.email_backend} host={s.smtp_host}:{s.smtp_port} security={s.smtp_security} user={who} password={pw} from={s.email_from}")
    for p in mail.config_problems():
        print("WARNING:", p)
    subject, text, html = mail_templates.test_email("python -m app.mailcheck")
    try:
        mail.send_email(argv[0], subject, text, html)
    except mail.MailError as exc:
        print("FAILED:", exc)
        return 1
    print("OK: handed to the mail server" if s.email_backend == "smtp" else "OK (console backend: written to the log only)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
