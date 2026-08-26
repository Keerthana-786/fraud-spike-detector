Repository diagnosis and remediation log

This document records a real issue discovered during development and the steps taken to diagnose and fix it. It is intentionally concise and factual so reviewers can verify work and reproduce the fix.

Issue: AttributeError: module 'hashlib' has no attribute 'scrypt'

- When: Observed while running the Streamlit dashboard and tests on macOS / Python 3.9/3.10 builds during local development.
- Symptom: Login and some tests failed with the traceback pointing at src/auth.py calls to hashlib.scrypt. The failure surfaced as an unhandled AttributeError which crashed the dashboard and failed unit tests.

Files involved:
- src/auth.py — previously used hashlib.scrypt() for password hashing and verification.
- app/dashboard.py — calls verify_password() during login flow causing the app to crash.
- tests/test_razorpay.py — unit test that exercised hash_password()/verify_password() and failed.

Diagnosis steps performed:
1. Reproduced the error by running pytest and observing failing tests and the AttributeError stack trace.
2. Opened src/auth.py and confirmed the code used hashlib.scrypt() to derive and verify password digests.
3. Checked local Python build for hashlib.scrypt availability (some builds and OS distributions do not expose scrypt through hashlib). Confirmed AttributeError occurs when hashlib.scrypt is not present.
4. Searched repository for references to scrypt and confirmed there were legacy scrypt-format hashes only in the authentication helpers — no other code critically depended on scrypt.

Root cause:
- The code called hashlib.scrypt unguarded. On Python builds that do not include scrypt in hashlib, calls raise AttributeError. This manifests as a crash when verifying passwords.

Resolution implemented:
1. Replaced new account hashing to use PBKDF2-HMAC-SHA256 (hashlib.pbkdf2_hmac) which is available reliably across Python builds. The new hash format is:
   pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>
   - iterations chosen = 200,000 (reasonable cost for modern machines; adjustable via code in the future).
2. Updated verify_password() to accept two formats:
   - pbkdf2_sha256$... (new default)
   - legacy scrypt$n$r$p$salt_b64$digest_b64 — verification attempts to use hashlib.scrypt if available; if hashlib.scrypt is not present, verify_password returns False (safe failure) rather than raising an exception.
3. Ensured verify_password returns False for unknown/unsupported algorithms instead of raising, preventing crashes in the dashboard and API.
4. Added unit tests (tests/test_live_pipeline.py) that exercise the pipeline and avoid requiring scrypt.

Why this fix is safe and appropriate:
- PBKDF2-HMAC-SHA256 is a widely supported, secure key-derivation option available across Python versions and platforms.
- Returning False for legacy scrypt hashes when scrypt is unavailable avoids crashes; it makes affected users reauthenticate or reset passwords. A migration path may be added later to rehash on successful scrypt verification on a host that supports it.
- The change is minimal, surgical, and preserves backwards compatibility when scrypt is available.

Verification performed:
- Ran full pytest suite locally: all tests pass after the fix (20 passed in local run during development).
- Manually exercised the Streamlit login flow to confirm the app no longer crashes on verify_password failures.

Next recommended actions (non-blocking):
- Provide an admin migration script to re-hash legacy scrypt password entries into the new pbkdf2 format. This requires either:
  - running the migration on a host that supports hashlib.scrypt, or
  - prompting users to reset passwords (safe, simple route when scrypt is unavailable).
- Optionally allow iterations/salt length to be configurable via system settings.

If you want, I can now:
- Add the admin migration script to convert scrypt hashes (requires a host with scrypt support), or
- Add an in-app migration that re-hashes on successful login when scrypt is available, or
- Leave as-is and document the user-facing reset-password guidance.

Created by: Copilot CLI runtime (local development assistance)
Timestamp: 2026-08-24
