"""Provider-neutral SMTP email notifications (password from env only)."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, Optional

from .audit import audit


PASSWORD_ENV = "AETHELGARD_SMTP_PASSWORD"


def settings_from_suite(suite: Dict[str, Any]) -> Dict[str, Any]:
    email = (suite or {}).get("email") or {}
    return {
        "enabled": bool(email.get("enabled")),
        "host": email.get("host") or os.environ.get("AETHELGARD_SMTP_HOST", ""),
        "port": int(email.get("port") or os.environ.get("AETHELGARD_SMTP_PORT") or 587),
        "username": email.get("username") or os.environ.get("AETHELGARD_SMTP_USERNAME", ""),
        "sender": email.get("sender") or os.environ.get("AETHELGARD_SMTP_SENDER", ""),
        "recipient": email.get("recipient") or os.environ.get("AETHELGARD_SMTP_RECIPIENT", ""),
        "tls_mode": (email.get("tls_mode") or "starttls").lower(),
        "password_env": PASSWORD_ENV,
        "password_configured": bool(os.environ.get(PASSWORD_ENV)),
    }


def _password() -> str:
    return os.environ.get(PASSWORD_ENV, "") or ""


def send_email(
    *,
    suite: Dict[str, Any],
    subject: str,
    body: str,
    force: bool = False,
) -> Dict[str, Any]:
    cfg = settings_from_suite(suite)
    if not cfg["enabled"] and not force:
        return {"ok": False, "skipped": True, "error": "Email notifications disabled"}
    if not cfg["host"] or not cfg["sender"] or not cfg["recipient"]:
        return {"ok": False, "error": "Email not configured (host/sender/recipient)"}
    password = _password()
    if cfg["username"] and not password:
        return {
            "ok": False,
            "error": f"SMTP password missing — set environment variable {PASSWORD_ENV}",
        }

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["recipient"]
    msg.set_content(body)

    try:
        if cfg["tls_mode"] == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=30) as smtp:
                if cfg["username"]:
                    smtp.login(cfg["username"], password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
                smtp.ehlo()
                if cfg["tls_mode"] in ("starttls", "tls", "true", "1"):
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if cfg["username"]:
                    smtp.login(cfg["username"], password)
                smtp.send_message(msg)
        audit("email.sent", subject=subject, recipient=cfg["recipient"])
        return {"ok": True, "recipient": cfg["recipient"]}
    except Exception as e:
        audit("email.failed", subject=subject, error=str(e))
        return {"ok": False, "error": str(e)}


def batch_completion_email(
    *,
    suite: Dict[str, Any],
    batch: Dict[str, Any],
    progress: Dict[str, Any],
    dashboard_url: str = "http://127.0.0.1:8080/",
) -> Dict[str, Any]:
    date = (batch.get("id") or "")[:10]
    subject = f"Aethelgard batch complete — {date} — {progress.get('listings_ready', 0)} listings"
    body = f"""Aethelgard batch reached a terminal state.

Batch ID: {batch.get('id')}
Status: {progress.get('status')}
Artworks: {progress.get('artworks_completed')}/{progress.get('artworks_total')}
Failures: {progress.get('artworks_failed')}
Listings ready: {progress.get('listings_ready')}/{progress.get('listings_total')}
Etsy drafts created: {progress.get('etsy_drafts')}
Attention required: {progress.get('listings_attention')}

Dashboard: {dashboard_url}
Batch Runs: {dashboard_url}#batch-runs

This message does not publish listings. Human review remains required.
"""
    return send_email(suite=suite, subject=subject, body=body)
