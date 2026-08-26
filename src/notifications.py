"""Optional email notifications for high-severity fraud alerts."""
from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from typing import Any, Iterable


def smtp_configured() -> bool:
    return all(os.getenv(name) for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "ALERT_FROM_EMAIL"))


def send_alert_email(alert: dict[str, Any], recipients: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    enabled = [item for item in recipients if item.get("enabled") and item.get("email")]
    if not enabled or not smtp_configured():
        return [{"recipient": item.get("email", ""), "status": "not_configured", "reason": "SMTP is not configured"} for item in enabled]
    message = EmailMessage()
    message["Subject"] = f"[SentinelPay] {alert.get('severity', 'High').title()} Fraud Spike Detected"
    message["From"] = os.environ["ALERT_FROM_EMAIL"]
    message["To"] = ", ".join(item["email"] for item in enabled)
    message.set_content(
        "Merchant payment activity requires attention.\n\n"
        f"Severity: {alert.get('severity', 'High')}\n"
        f"Detected: {alert.get('detected_at', 'Not available')}\n"
        f"Current fraud rate: {float(alert.get('current_rate', 0)):.2%}\n"
        f"Normal baseline: {float(alert.get('baseline_rate', 0)):.2%}\n"
        f"Affected transactions: {alert.get('affected_transactions', 'Not available')}\n"
        f"Estimated exposure: {alert.get('potential_exposure', 'Not available')}\n\n"
        "Recommended action: Review the affected transactions in SentinelPay."
    )
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls()
            server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            server.send_message(message)
        return [{"recipient": item["email"], "status": "sent", "reason": ""} for item in enabled]
    except Exception:
        return [{"recipient": item["email"], "status": "failed", "reason": "Email service unavailable"} for item in enabled]
