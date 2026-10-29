"""Sends account emails (password reset, invites).

Two ways, whichever is configured:
- Brevo's HTTP API (BREVO_API_KEY): free for 300 emails a day, and works on hosts that block
  SMTP ports, such as Render's free tier.
- Plain SMTP (SMTP_HOST and friends).
Without either, the link is logged (and shown on screen in development), so nothing ever blocks."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from ..config import settings

log = logging.getLogger("tripreports.mail")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _sender_name(name: str | None = None) -> str:
    return (name or settings.mail_from_name or settings.name_for("es"))[:70]


def _send_brevo(to: str, subject: str, body: str, html: str | None = None, sender_name: str | None = None,
                reply_to: str | None = None) -> bool:
    payload = {
        "sender": {"email": settings.mail_from, "name": _sender_name(sender_name)},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }
    if html:
        payload["htmlContent"] = html
    if reply_to or settings.support_email:
        payload["replyTo"] = {"email": reply_to or settings.support_email}
    r = httpx.post(BREVO_URL, json=payload, timeout=15,
                   headers={"api-key": settings.brevo_api_key, "accept": "application/json"})
    if r.status_code >= 300:
        log.warning("Brevo refused the email to %s: %s %s", to, r.status_code, r.text[:300])
        return False
    return True


def _send_smtp(to: str, subject: str, body: str, html: str | None = None, sender_name: str | None = None,
               reply_to: str | None = None) -> bool:
    msg = EmailMessage()
    msg["From"] = formataddr((_sender_name(sender_name), settings.mail_from))
    msg["To"], msg["Subject"] = to, subject
    if reply_to or settings.support_email:
        msg["Reply-To"] = reply_to or settings.support_email
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        s.starttls()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
    return True


def send(to: str, subject: str, body: str, html: str | None = None, sender_name: str | None = None,
         reply_to: str | None = None) -> bool:
    if not settings.mail_enabled:
        log.info("Email to %s not sent (no email service configured): %s\n%s", to, subject, body)
        return False
    try:
        if settings.brevo_api_key:
            return _send_brevo(to, subject, body, html, sender_name, reply_to)
        return _send_smtp(to, subject, body, html, sender_name, reply_to)
    except Exception as e:  # never break a request because email failed
        log.warning("Email to %s failed: %s", to, e)
        return False
