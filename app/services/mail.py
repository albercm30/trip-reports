"""Sends account emails (password reset, invites) over SMTP when configured.
Without SMTP the link is logged and shown on screen, so nothing ever blocks."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

log = logging.getLogger("tripreports.mail")


def send(to: str, subject: str, body: str) -> bool:
    if not settings.mail_enabled:
        log.info("Email to %s not sent (SMTP not configured): %s\n%s", to, subject, body)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.mail_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except Exception as e:  # never break a request because email failed
        log.warning("Email to %s failed: %s", to, e)
        return False
