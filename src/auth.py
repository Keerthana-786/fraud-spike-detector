"""Authentication and security helpers for SentinelPay.

Provides salted PBKDF2-HMAC-SHA256 password hashing, token generation,
session management with Remember-Me capability, and strict registration validation.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
from typing import Optional

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECRET_KEY = os.getenv("SECRET_KEY", "sentinelpay-production-secret-key-salt-2026")


def valid_email(email: str) -> bool:
    """Validate email address format strictly."""
    return bool(EMAIL_RE.fullmatch(email.strip().lower()))


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with random 16-byte salt.

    Returns string format: pbkdf2_sha256$iterations$salt_b64$digest_b64
    """
    salt = os.urandom(16)
    iterations = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify plaintext password against encoded hash."""
    if not encoded or not password:
        return False
    try:
        parts = encoded.split("$")
        algorithm = parts[0]
        if algorithm == "pbkdf2_sha256":
            _, iterations_text, salt_text, digest_text = parts
            iterations = int(iterations_text)
            salt = base64.urlsafe_b64decode(salt_text.encode())
            expected = base64.urlsafe_b64decode(digest_text.encode())
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        if algorithm == "scrypt":
            try:
                _, n_text, r_text, p_text, salt_text, digest_text = parts
                n, r, p = int(n_text), int(r_text), int(p_text)
                salt = base64.urlsafe_b64decode(salt_text.encode())
                expected = base64.urlsafe_b64decode(digest_text.encode())
                if not hasattr(hashlib, "scrypt"):
                    return False
                actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p)
                return hmac.compare_digest(actual, expected)
            except (ValueError, TypeError, AttributeError):
                return False
        return False
    except (ValueError, TypeError):
        return False


def validate_registration(
    full_name: str,
    email: str,
    password: str,
    confirmation: str,
    organization: str,
    role: str,
    terms: bool,
) -> Optional[str]:
    """Validate all user signup fields strictly."""
    if not full_name or not full_name.strip():
        return "Please enter your full name."
    if not email or not valid_email(email):
        return "Enter a valid email address."
    if not organization or not organization.strip():
        return "Please enter your organization name."
    if role not in {
        "Merchant Admin",
        "Risk Analyst",
        "Security Analyst",
        "Finance Manager",
        "Operations Manager",
        "merchant_user",
        "Merchant User",
    }:
        return "Select a valid role."
    if len(password) < 8:
        return "Password must contain at least 8 characters."
    if password != confirmation:
        return "Passwords do not match."
    if not terms:
        return "Accept the Terms and Privacy Policy to continue."
    return None


def create_session_token(user_id: str, email: str, role: str, remember_me: bool = False) -> str:
    """Create a signed, tamper-proof session token with expiry."""
    lifetime_days = 30 if remember_me else 1
    expires_at = (datetime.now(timezone.utc) + timedelta(days=lifetime_days)).isoformat()
    payload = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "role": role,
        "remember_me": remember_me,
        "exp": expires_at,
        "nonce": secrets.token_hex(8),
    }
    raw = json.dumps(payload, sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(raw.encode("utf-8")).decode()
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str) -> Optional[dict]:
    """Verify session token integrity and return payload if valid and not expired."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode())
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp_time = datetime.fromisoformat(payload["exp"])
        if datetime.now(timezone.utc) > exp_time:
            return None
        return payload
    except Exception:
        return None
