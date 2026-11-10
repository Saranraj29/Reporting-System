# Email: setup, what is sent, troubleshooting

## What the app sends
| Email | When | Link valid |
|---|---|---|
| Confirm your email address | registration (and "Resend verification email") | 48 hours |
| Reset your password | "Forgot password" | 1 hour, works once |
| *Name* invited you to *Company* | an admin invites a user (Users → Invite by email) | 7 days |
| Your password was changed | password changed on the Profile page or through a reset link | – (security notice) |
| Reminders, report emails | the worker (morning plan, due dates, scheduled reports) | – |

All of them are sent by the worker from a queue: a slow or failing mail server never blocks a request, a failed send is retried (5 attempts with
growing back-off) and the result is written to Settings → Notification log. Each message has an HTML and a plain-text part; names are HTML-escaped.
Tokens and links are created at send time, so no secret is stored in the job table.

The "Development mode: open link" shortcut on the verify / reset screens exists **only while `EMAIL_BACKEND=console`**. With `smtp` the link is never returned
by the API: the only way to get it is the email.

## Turn on real email
Put these in a `.env` file next to `docker-compose.yml` (it is git-ignored — **never commit it**), then `docker compose up -d --force-recreate api worker worker-ai`:

```
EMAIL_BACKEND=smtp
EMAIL_FROM=Project Transparency <no-reply@yourcompany.com>
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587            # 587 + starttls, or 465 + ssl
SMTP_SECURITY=starttls   # starttls | ssl | none
SMTP_USER=...
SMTP_PASSWORD=...
PUBLIC_WEB_URL=https://app.yourcompany.com   # the address people open; links in emails start with it
APP_ENV=prod             # production mode (stricter defaults)
```

Check it three ways:
1. Settings → **Email delivery** shows the mode and any problem, and **Send a test email to me** delivers one right now (errors are explained: wrong password, host unreachable, TLS mismatch, sender refused).
2. `docker compose exec api python -m app.mailcheck you@yourcompany.com`
3. `docker compose logs api worker | grep -i "email"` — start-up warnings appear as `email configuration: …`.

## Providers
* **Gmail / Google Workspace**: `smtp.gmail.com`, 587/starttls, an *App Password* (2-step verification must be on), `EMAIL_FROM` must be the same address (or an alias you configured).
* **Amazon SES**: `email-smtp.<region>.amazonaws.com`, 587/starttls, SMTP credentials (not IAM keys), a verified sender/domain, and production access (out of the sandbox).
* **Microsoft 365**: `smtp.office365.com`, 587/starttls, SMTP AUTH enabled for the mailbox.

## Deliverability (so mail does not land in spam)
Send from a domain you own, and set **SPF**, **DKIM** and **DMARC** for it with your provider's records. The app sends `Auto-Submitted: auto-generated` and a
unique `Message-ID`, uses a no-reply sender (set `EMAIL_REPLY_TO` if people should be able to answer) and never puts passwords in a message.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Nothing arrives, "Development mode" in Settings | `EMAIL_BACKEND` is still `console` |
| "rejected the username or password" | wrong credentials, or an App Password is needed |
| "Could not reach the mail server" | wrong `SMTP_HOST`/`SMTP_PORT`, or the network blocks outbound SMTP |
| "Secure connection … failed" | port/security mismatch: 587 ↔ starttls, 465 ↔ ssl |
| "refused the sender address" | `EMAIL_FROM` is not an address your account may send from |
| Arrives in spam | SPF/DKIM/DMARC not set for the sending domain |
