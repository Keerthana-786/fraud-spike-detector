"""SQLite persistence and domain store for SentinelPay risk intelligence."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Optional

from src.auth import hash_password

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "fraudpulse_live.sqlite3"

DEFAULT_SYSTEM_SETTINGS: dict[str, str] = {
    "fraud_classification_threshold": "0.50",
    "min_transactions": "20",
    "baseline_window": "24",
    "min_history_buckets": "12",
    "zscore_threshold": "3.0",
    "cost_per_false_positive": "50.0",
    "cost_per_missed_spike": "5000.0",
    "average_loss_rate": "0.60",
    "require_admin_approval": "0",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso_timestamp(value: Any) -> str:
    """Normalize SQLite CURRENT_TIMESTAMP or ISO strings to a real ISO-8601 value."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    return text


def _sql_finite_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """SQLite REAL cannot store NaN/Inf; those bind as NULL. Always coerce to a finite float."""
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _multiplier_from_slice(slice_attr: Any) -> Optional[float]:
    if isinstance(slice_attr, str):
        try:
            slice_attr = json.loads(slice_attr or "{}")
        except Exception:
            return None
    if not isinstance(slice_attr, dict):
        return None
    top = slice_attr.get("top_slice") or {}
    return _sql_finite_float(top.get("multiplier"))


def _ensure_alert_multiplier(alert: dict) -> dict:
    """Write a finite multiplier onto the alert dict before INSERT/UPDATE."""
    coerced = _sql_finite_float(alert.get("multiplier"))
    if coerced is None or coerced <= 0:
        coerced = _multiplier_from_slice(alert.get("slice_attribution") or alert.get("slice_attribution_json"))
    if coerced is None or coerced <= 0:
        coerced = _sql_finite_float(alert.get("anomaly_score"), default=1.0) or 1.0
    alert["multiplier"] = round(float(coerced), 1)
    return alert


def _hydrate_alert_multiplier(alert: dict) -> dict:
    if _sql_finite_float(alert.get("multiplier")) is None:
        derived = _multiplier_from_slice(alert.get("slice_attribution") or alert.get("slice_attribution_json"))
        if derived is not None:
            alert["multiplier"] = round(derived, 1)
    return alert


def _serialize_audit_event(row: dict) -> dict:
    iso = _to_iso_timestamp(row.get("occurred_at") or row.get("created_at") or row.get("timestamp"))
    row["occurred_at"] = iso
    row["timestamp"] = iso
    return row


class LiveStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL DEFAULT 'Merchant Admin',
                    password_hash TEXT,
                    organization TEXT,
                    terms_accepted INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    email_verified INTEGER NOT NULL DEFAULT 1,
                    email_verified_at TEXT,
                    last_login_at TEXT,
                    created_via TEXT NOT NULL DEFAULT 'BOOTSTRAP',
                    deleted_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    product_id TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount > 0),
                    currency TEXT NOT NULL DEFAULT 'INR',
                    status TEXT NOT NULL DEFAULT 'created',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount >= 0),
                    currency TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    order_id TEXT,
                    customer_id TEXT,
                    source TEXT NOT NULL,
                    raw_event_id TEXT UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS fraud_predictions (
                    transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id),
                    fraud_probability REAL,
                    risk_level TEXT NOT NULL,
                    model_status TEXT NOT NULL,
                    explanation_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS time_buckets (
                    bucket_start TEXT NOT NULL,
                    source TEXT NOT NULL,
                    transaction_count INTEGER NOT NULL,
                    suspicious_count INTEGER NOT NULL,
                    fraud_rate REAL NOT NULL,
                    baseline_rate REAL,
                    stddev REAL,
                    z_score REAL NOT NULL,
                    PRIMARY KEY(bucket_start, source)
                );

                CREATE TABLE IF NOT EXISTS spike_alerts (
                    alert_id TEXT PRIMARY KEY,
                    detected_at TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    source TEXT NOT NULL,
                    baseline_rate REAL NOT NULL,
                    current_rate REAL NOT NULL,
                    multiplier REAL,
                    anomaly_score REAL NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'INVESTIGATING',
                    affected_transactions INTEGER NOT NULL,
                    potential_exposure REAL NOT NULL,
                    root_cause_json TEXT NOT NULL DEFAULT '[]',
                    slice_attribution_json TEXT NOT NULL DEFAULT '{}',
                    timeline_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS investigation_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL REFERENCES spike_alerts(alert_id),
                    note TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'merchant_operator',
                    details TEXT,
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notification_recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT,
                    recipient TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failure_reason TEXT,
                    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
                CREATE INDEX IF NOT EXISTS idx_transactions_source ON transactions(source);
                CREATE INDEX IF NOT EXISTS idx_alerts_detected_at ON spike_alerts(detected_at);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON spike_alerts(status);
                CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_events(occurred_at);
            """)

            # Auto-migrate any missing columns on pre-existing database files
            existing_audit = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
            if "details" not in existing_audit:
                conn.execute("ALTER TABLE audit_events ADD COLUMN details TEXT")
            if "occurred_at" not in existing_audit:
                conn.execute("ALTER TABLE audit_events ADD COLUMN occurred_at TEXT")
                source_ts = "created_at" if "created_at" in existing_audit else None
                if source_ts:
                    conn.execute(
                        "UPDATE audit_events SET occurred_at = created_at WHERE occurred_at IS NULL OR occurred_at = ''"
                    )
                conn.execute(
                    "UPDATE audit_events SET occurred_at = CURRENT_TIMESTAMP WHERE occurred_at IS NULL OR occurred_at = ''"
                )

            existing_users = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            for col, defn in {
                "password_hash": "TEXT", "organization": "TEXT", "updated_at": "TEXT", "terms_accepted": "INTEGER NOT NULL DEFAULT 0",
                "status": "TEXT NOT NULL DEFAULT 'ACTIVE'", "email_verified": "INTEGER NOT NULL DEFAULT 1",
                "email_verified_at": "TEXT", "last_login_at": "TEXT", "created_via": "TEXT NOT NULL DEFAULT 'BOOTSTRAP'", "deleted_at": "TEXT",
            }.items():
                if col not in existing_users:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

            existing_alerts = {row[1] for row in conn.execute("PRAGMA table_info(spike_alerts)").fetchall()}
            for col, defn in {
                "updated_at": "TEXT",
                "status": "TEXT DEFAULT 'INVESTIGATING'",
                "slice_attribution_json": "TEXT DEFAULT '{}'",
                "timeline_json": "TEXT DEFAULT '[]'",
            }.items():
                if col not in existing_alerts:
                    conn.execute(f"ALTER TABLE spike_alerts ADD COLUMN {col} {defn}")

            existing_recipients = {row[1] for row in conn.execute("PRAGMA table_info(notification_recipients)").fetchall()}
            if "updated_at" not in existing_recipients:
                conn.execute("ALTER TABLE notification_recipients ADD COLUMN updated_at TEXT")

            # Seed default system settings if missing
            for key, val in DEFAULT_SYSTEM_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO system_settings(key, value) VALUES (?, ?)",
                    (key, val),
                )

            # Seed default admin and team users if no admin exists
            admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('Merchant Admin', 'ADMIN') AND status = 'ACTIVE' AND deleted_at IS NULL").fetchone()[0])
            if admin_count == 0:
                clean_team = [
                    ("USER_ADMIN", "System Administrator", "admin@sentinelpay.internal", "Merchant Admin", hash_password("AdminSecurePassword123!"), "SentinelPay Platform", "ACTIVE", 1),
                    ("USER_KEERTHANA", "Keerthana R.", "keerthana@sentinelpay.internal", "Risk Analyst", hash_password("KeerthanaSecure123!"), "Risk Operations Desk", "ACTIVE", 1),
                    ("USER_FINANCE", "Cyrus V.", "finance@sentinelpay.internal", "Finance Manager", hash_password("FinanceSecure123!"), "Merchant Finance Desk", "ACTIVE", 1),
                    ("USER_OPS", "Priya Sharma", "operations@sentinelpay.internal", "Operations Manager", hash_password("OpsSecure123!"), "Merchant Operations", "ACTIVE", 1),
                ]
                for uid, name, email, role, pwd, org, status, ver in clean_team:
                    conn.execute(
                        "INSERT OR IGNORE INTO users(user_id, name, email, role, password_hash, organization, terms_accepted, status, email_verified, created_via) "
                        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'BOOTSTRAP')",
                        (uid, name, email, role, pwd, org, status, ver),
                    )

            # Seed default notification recipient if empty
            rec_count = int(conn.execute("SELECT COUNT(*) FROM notification_recipients").fetchone()[0])
            if rec_count == 0:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_recipients(name, email, role, enabled) "
                    "VALUES ('Risk Operations Desk', 'security@sentinelpay.internal', 'Security Operations', 1)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO notification_recipients(name, email, role, enabled) "
                    "VALUES ('Keerthana R. (Lead Analyst)', 'keerthana@sentinelpay.internal', 'Risk Analyst', 1)"
                )

    # -------------------------------------------------------------------------
    # System Settings
    # -------------------------------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> str:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
            if row:
                return row["value"]
            return default if default is not None else DEFAULT_SYSTEM_SETTINGS.get(key, "")

    def get_all_settings(self) -> dict[str, str]:
        settings = dict(DEFAULT_SYSTEM_SETTINGS)
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
            for r in rows:
                settings[r["key"]] = r["value"]
        return settings

    get_settings = get_all_settings

    def update_settings(self, new_settings: dict[str, Any], actor: str = "Merchant Admin") -> dict[str, Any]:
        changes = {}
        with self.connection() as conn:
            for k, v in new_settings.items():
                old_row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (k,)).fetchone()
                old_val = old_row["value"] if old_row else None
                val_str = str(v)
                conn.execute(
                    "INSERT INTO system_settings(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                    (k, val_str),
                )
                changes[k] = {"before": old_val, "after": val_str}
        self.record_audit(
            alert_id=None,
            action="SETTINGS_CHANGED",
            actor=actor,
            details=json.dumps(changes),
        )
        return changes

    # -------------------------------------------------------------------------
    # User & Auth Persistence
    # -------------------------------------------------------------------------
    def save_user(
        self,
        user_id: str,
        name: str,
        email: str,
        role: str = "Merchant Admin",
        password_hash: Optional[str] = None,
        organization: Optional[str] = None,
        terms_accepted: bool = False,
        status: str = "ACTIVE",
        email_verified: bool = True,
        created_via: str = "BOOTSTRAP",
    ) -> None:
        email_clean = email.strip().lower()
        with self.connection() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE email = ?", (email_clean,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE users SET
                       name = ?,
                       role = ?,
                       password_hash = COALESCE(?, password_hash),
                       organization = COALESCE(?, organization),
                       terms_accepted = ?, status = ?, email_verified = ?, created_via = ?,
                       updated_at = CURRENT_TIMESTAMP
                       WHERE email = ?""",
                    (
                        name.strip(),
                        role,
                        password_hash,
                        organization.strip() if organization else None,
                        int(terms_accepted),
                        status,
                        int(email_verified),
                        created_via,
                        email_clean,
                    ),
                )
            else:
                conn.execute(
                          """INSERT INTO users(user_id, name, email, role, password_hash, organization, terms_accepted, status, email_verified, created_via, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id) DO UPDATE SET
                           name = excluded.name,
                           email = excluded.email,
                           role = excluded.role,
                           password_hash = COALESCE(excluded.password_hash, users.password_hash),
                           organization = COALESCE(excluded.organization, users.organization),
                           terms_accepted = excluded.terms_accepted,
                           status = excluded.status,
                           email_verified = excluded.email_verified,
                           created_via = excluded.created_via,
                           updated_at = CURRENT_TIMESTAMP""",
                    (
                        user_id,
                        name.strip(),
                        email_clean,
                        role,
                        password_hash,
                        organization.strip() if organization else None,
                        int(terms_accepted),
                        status,
                        int(email_verified),
                        created_via,
                    ),
                )

    def user_by_email(self, email: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT user_id, name, email, role, organization, status, email_verified, email_verified_at, created_at, last_login_at, created_via, deleted_at FROM users WHERE deleted_at IS NULL ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

    def active_admin_count(self) -> int:
        with self.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('Merchant Admin', 'ADMIN') AND status = 'ACTIVE' AND deleted_at IS NULL").fetchone()[0])

    def update_user(self, user_id: str, *, role: Optional[str] = None, status: Optional[str] = None, actor: str = "Merchant Admin") -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
            if not row:
                return None
            before = dict(row)
            next_role = role or before["role"]
            next_status = status or before["status"]
            admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('Merchant Admin', 'ADMIN') AND status = 'ACTIVE' AND deleted_at IS NULL").fetchone()[0])
            if before["role"] in {"Merchant Admin", "ADMIN"} and before["status"] == "ACTIVE" and (next_role not in {"Merchant Admin", "ADMIN"} or next_status != "ACTIVE") and admin_count <= 1:
                raise ValueError("At least one administrator account must remain active.")
            conn.execute("UPDATE users SET role = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (next_role, next_status, user_id))
            if next_status != "ACTIVE":
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            after = dict(before, role=next_role, status=next_status)
        action = "ROLE_CHANGED" if before["role"] != next_role else ("USER_ENABLED" if next_status == "ACTIVE" else "USER_DISABLED")
        self.record_audit(None, action, actor=actor, details=json.dumps({"user_id": user_id, "before": {"role": before["role"], "status": before["status"]}, "after": {"role": next_role, "status": next_status}}))
        return after

    def soft_delete_user(self, user_id: str, actor: str) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT role, status FROM users WHERE user_id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
            if not row:
                return False
            admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('Merchant Admin', 'ADMIN') AND status = 'ACTIVE' AND deleted_at IS NULL").fetchone()[0])
            if row["role"] in {"Merchant Admin", "ADMIN"} and row["status"] == "ACTIVE" and admin_count <= 1:
                raise ValueError("At least one administrator account must remain active.")
            conn.execute("UPDATE users SET status = 'DISABLED', deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.record_audit(None, "USER_DEACTIVATED", actor=actor, details=json.dumps({"user_id": user_id}))
        return True

    def create_verification_token(self, user_id: str, token: str, expires_at: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO email_verification_tokens(token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires_at))

    def verify_email_token(self, token: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM email_verification_tokens WHERE token = ? AND used_at IS NULL", (token,)).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
                return None
            conn.execute("UPDATE email_verification_tokens SET used_at = ? WHERE token = ?", (_iso_now(), token))
            conn.execute("UPDATE users SET email_verified = 1, email_verified_at = ?, status = CASE WHEN status = 'PENDING_VERIFICATION' THEN 'ACTIVE' ELSE status END, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (_iso_now(), row["user_id"]))
            return dict(conn.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone())

    def create_password_reset_token(self, user_id: str, token: str, expires_at: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO password_reset_tokens(token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires_at))

    def reset_password_with_token(self, token: str, new_password_hash: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM password_reset_tokens WHERE token = ? AND used_at IS NULL", (token,)).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
                return None
            conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE token = ?", (_iso_now(), token))
            conn.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (new_password_hash, row["user_id"]))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            user = dict(conn.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone())
        self.record_audit(None, "PASSWORD_RESET_COMPLETED", actor=user["email"], details=json.dumps({"user_id": user["user_id"]}))
        return user

    def invalidate_user_sessions(self, user_id: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def next_user_id(self) -> str:
        with self.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return f"USER_{int(count) + 1:03d}"

    def save_session(self, token: str, user_id: str, expires_at: Optional[str] = None) -> None:
        if not expires_at or expires_at == "1d":
            exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        elif expires_at == "30d":
            exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        else:
            exp = expires_at
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, exp),
            )

    def get_session(self, token: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
            if not row:
                return None
            try:
                exp_str = row["expires_at"]
                if exp_str and "T" in exp_str:
                    exp_dt = datetime.fromisoformat(exp_str)
                    if exp_dt < datetime.now(timezone.utc):
                        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                        return None
            except Exception:
                pass
            return dict(row)

    def delete_session(self, token: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    # -------------------------------------------------------------------------
    # Orders & Webhook Tracking
    # -------------------------------------------------------------------------
    def event_seen(self, event_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone() is not None

    def record_event(self, event_id: str, event_type: str, received_at: Optional[str] = None) -> None:
        received = received_at or datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO webhook_events(event_id, event_type, received_at) VALUES (?, ?, ?)",
                (event_id, event_type, received),
            )

    def save_order(self, order_id: str, user_id: str, product_id: str, amount: float, currency: str = "INR") -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO orders(order_id, user_id, product_id, amount, currency) VALUES (?, ?, ?, ?, ?)",
                (order_id, user_id, product_id, amount, currency),
            )

    def order_user(self, order_id: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT o.*, u.name, u.email, u.role FROM orders o JOIN users u ON u.user_id = o.user_id WHERE o.order_id = ?",
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    # -------------------------------------------------------------------------
    # Transactions & Predictions
    # -------------------------------------------------------------------------
    def store_transaction(self, transaction: dict) -> bool:
        normalized = {
            "order_id": None,
            "customer_id": None,
            "raw_event_id": None,
            **transaction,
        }
        with self.connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO transactions
                    (transaction_id, timestamp, amount, currency, payment_method, status, order_id, customer_id, source, raw_event_id)
                    VALUES (:transaction_id, :timestamp, :amount, :currency, :payment_method, :status, :order_id, :customer_id, :source, :raw_event_id)""",
                    normalized,
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def update_transaction_status(self, transaction_id: str, status: str, raw_event_id: Optional[str] = None) -> bool:
        with self.connection() as conn:
            res = conn.execute(
                "UPDATE transactions SET status = ?, raw_event_id = COALESCE(?, raw_event_id) WHERE transaction_id = ?",
                (status, raw_event_id, transaction_id),
            )
        return res.rowcount > 0

    def store_prediction(self, transaction_id: str, prediction: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO fraud_predictions
                (transaction_id, fraud_probability, risk_level, model_status, explanation_json)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    transaction_id,
                    prediction.get("fraud_probability"),
                    prediction.get("risk_level", "LOW"),
                    prediction.get("model_status", "scored"),
                    json.dumps(prediction.get("explanation", [])),
                ),
            )

    def get_prediction(self, transaction_id: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM fraud_predictions WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_transaction(self, transaction_id: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                """SELECT t.*, p.fraud_probability, p.risk_level, p.model_status, p.explanation_json
                   FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE t.transaction_id = ?""",
                (transaction_id,),
            ).fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["explanation"] = json.loads(res.get("explanation_json") or "[]")
        except Exception:
            res["explanation"] = []
        return res

    def recent_transactions(self, limit: int = 100, source: Optional[str] = None) -> list[dict]:
        with self.connection() as conn:
            if source:
                rows = conn.execute(
                    """SELECT t.*, p.fraud_probability, p.risk_level, p.model_status, p.explanation_json
                       FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                       WHERE t.source = ?
                       ORDER BY t.timestamp DESC, t.id DESC LIMIT ?""",
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT t.*, p.fraud_probability, p.risk_level, p.model_status, p.explanation_json
                       FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                       ORDER BY t.timestamp DESC, t.id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["explanation"] = json.loads(d.get("explanation_json") or "[]")
            except Exception:
                d["explanation"] = []
            result.append(d)
        return result

    def transactions_for_bucket(self, bucket_start: str, source: str, limit: int = 200) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT t.*, p.fraud_probability, p.risk_level, p.model_status, p.explanation_json
                   FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE strftime('%Y-%m-%dT%H:00:00', t.timestamp) = ? AND t.source = ?
                   ORDER BY p.fraud_probability DESC, t.amount DESC LIMIT ?""",
                (bucket_start, source, limit),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["explanation"] = json.loads(d.get("explanation_json") or "[]")
            except Exception:
                d["explanation"] = []
            result.append(d)
        return result

    def compute_slice_attribution(self, bucket_start: str, source: str) -> dict:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT t.payment_method,
                          COUNT(t.id) as slice_total,
                          COALESCE(SUM(CASE WHEN p.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END), 0) as slice_suspicious
                   FROM transactions t
                   LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE strftime('%Y-%m-%dT%H:00:00', t.timestamp) = ? AND t.source = ?
                   GROUP BY t.payment_method""",
                (bucket_start, source),
            ).fetchall()

            hist_rows = conn.execute(
                """SELECT t.payment_method,
                          COUNT(t.id) as hist_total,
                          COALESCE(SUM(CASE WHEN p.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END), 0) as hist_suspicious
                   FROM transactions t
                   LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE strftime('%Y-%m-%dT%H:00:00', t.timestamp) < ? AND t.source = ?
                   GROUP BY t.payment_method""",
                (bucket_start, source),
            ).fetchall()

        hist_rates = {}
        for r in hist_rows:
            htot = int(r["hist_total"])
            hsusp = int(r["hist_suspicious"])
            hist_rates[r["payment_method"]] = (hsusp / htot) if htot >= 10 else 0.005

        total_suspicious_in_bucket = sum(int(r["slice_suspicious"]) for r in rows)
        if total_suspicious_in_bucket == 0 or not rows:
            return {}

        candidates = []
        for r in rows:
            method = r["payment_method"]
            stot = int(r["slice_total"])
            ssusp = int(r["slice_suspicious"])
            if stot < 3 or ssusp == 0:
                continue
            cur_rate = ssusp / stot
            base_rate = hist_rates.get(method, 0.005)
            share_pct = (ssusp / total_suspicious_in_bucket) * 100.0
            volume_weighted_deviation = share_pct * max(0.0, cur_rate - base_rate)
            candidates.append({
                "dimension": "Payment Channel",
                "slice_value": method,
                "slice_total": stot,
                "slice_suspicious": ssusp,
                "share_pct": round(share_pct, 1),
                "slice_baseline": round(base_rate, 4),
                "current_rate": round(cur_rate, 4),
                "multiplier": round(cur_rate / base_rate, 1) if base_rate > 0 else None,
                "score": volume_weighted_deviation,
            })

        if not candidates:
            return {}

        top_slice = max(candidates, key=lambda x: x["score"])
        narrative = (
            f"Payment Channel '{top_slice['slice_value']}': {top_slice['share_pct']}% of this spike's affected transactions. "
            f"Slice baseline {top_slice['slice_baseline']:.1%}, current {top_slice['current_rate']:.1%}"
            f" ({top_slice['multiplier']}x normal)." if top_slice.get('multiplier') else ""
        )
        return {
            "top_slice": top_slice,
            "all_slices": candidates,
            "narrative": narrative,
        }

    # -------------------------------------------------------------------------
    # Time Buckets & Spikes
    # -------------------------------------------------------------------------
    def upsert_bucket(self, bucket: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO time_buckets
                (bucket_start, source, transaction_count, suspicious_count, fraud_rate, baseline_rate, stddev, z_score)
                VALUES (:bucket_start, :source, :transaction_count, :suspicious_count, :fraud_rate, :baseline_rate, :stddev, :z_score)""",
                bucket,
            )

    def bucket_counts(self, bucket_start: str, source: str) -> tuple[int, int]:
        with self.connection() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(CASE WHEN p.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END), 0) AS suspicious
                   FROM transactions t JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE strftime('%Y-%m-%dT%H:00:00', t.timestamp) = ? AND t.source = ?""",
                (bucket_start, source),
            ).fetchone()
        return int(row["total"]), int(row["suspicious"])

    def recent_bucket_rows(self, source: str, before: str, limit: int = 24) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """SELECT * FROM time_buckets WHERE source = ? AND bucket_start < ?
                   ORDER BY bucket_start DESC LIMIT ?""",
                (source, before, limit),
            ).fetchall()

    def all_time_buckets(self, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM time_buckets ORDER BY bucket_start ASC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Alerts & Investigations
    # -------------------------------------------------------------------------
    def alert_exists(self, bucket_start: str, source: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM spike_alerts WHERE window_start = ? AND source = ?",
                (bucket_start, source),
            ).fetchone()
        return dict(row) if row else None

    def create_alert(self, alert: dict, actor: str = "SentinelPay Alert Engine") -> None:
        alert_payload = _ensure_alert_multiplier({
            "slice_attribution_json": "{}",
            "timeline_json": "[]",
            **alert,
        })
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO spike_alerts
                (alert_id, detected_at, window_start, window_end, source, baseline_rate, current_rate,
                 multiplier, anomaly_score, severity, status, affected_transactions, potential_exposure,
                 root_cause_json, slice_attribution_json, timeline_json, updated_at)
                VALUES (:alert_id, :detected_at, :window_start, :window_end, :source, :baseline_rate, :current_rate,
                        :multiplier, :anomaly_score, :severity, :status, :affected_transactions, :potential_exposure,
                        :root_cause_json, :slice_attribution_json, :timeline_json, CURRENT_TIMESTAMP)""",
                alert_payload,
            )
        self.record_audit(
            alert["alert_id"],
            "Alert created",
            actor=actor,
            details=f"{alert['severity']} severity anomaly (Z={alert['anomaly_score']:.1f})",
        )

    def update_alert(self, alert: dict, escalation: bool = False, actor: str = "SentinelPay Alert Engine") -> None:
        alert_payload = _ensure_alert_multiplier({
            "slice_attribution_json": "{}",
            "timeline_json": "[]",
            **alert,
        })
        with self.connection() as conn:
            conn.execute(
                """UPDATE spike_alerts SET
                    window_end = :window_end,
                    current_rate = :current_rate,
                    multiplier = :multiplier,
                    anomaly_score = :anomaly_score,
                    severity = :severity,
                    affected_transactions = :affected_transactions,
                    potential_exposure = :potential_exposure,
                    root_cause_json = :root_cause_json,
                    slice_attribution_json = :slice_attribution_json,
                    timeline_json = :timeline_json,
                    updated_at = CURRENT_TIMESTAMP
                   WHERE alert_id = :alert_id""",
                alert_payload,
            )
        if escalation:
            self.record_audit(
                alert["alert_id"],
                "ALERT_ESCALATED",
                actor=actor,
                details=f"Severity escalated to {alert['severity']}",
            )

    def get_alert(self, alert_id: str) -> Optional[dict]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM spike_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["root_cause"] = json.loads(res.get("root_cause_json") or "[]")
        except Exception:
            res["root_cause"] = []
        try:
            res["slice_attribution"] = json.loads(res.get("slice_attribution_json") or "{}")
        except Exception:
            res["slice_attribution"] = {}
        try:
            res["timeline"] = json.loads(res.get("timeline_json") or "[]")
        except Exception:
            res["timeline"] = []
        return _hydrate_alert_multiplier(res)

    def list_alerts(
        self,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM spike_alerts WHERE 1=1"
        params: list[Any] = []
        if severity and severity != "ALL":
            query += " AND severity = ?"
            params.append(severity)
        if status and status != "ALL":
            query += " AND status = ?"
            params.append(status)
        if source and source != "ALL":
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["root_cause"] = json.loads(d.get("root_cause_json") or "[]")
            except Exception:
                d["root_cause"] = []
            try:
                d["slice_attribution"] = json.loads(d.get("slice_attribution_json") or "{}")
            except Exception:
                d["slice_attribution"] = {}
            try:
                d["timeline"] = json.loads(d.get("timeline_json") or "[]")
            except Exception:
                d["timeline"] = []
            result.append(_hydrate_alert_multiplier(d))
        return result

    def update_alert_status(
        self,
        alert_id: str,
        status: str,
        note: Optional[str] = None,
        actor: str = "Merchant Admin",
    ) -> bool:
        with self.connection() as conn:
            res = conn.execute(
                "UPDATE spike_alerts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE alert_id = ?",
                (status, alert_id),
            )
            if res.rowcount == 0:
                return False
            if note:
                conn.execute(
                    "INSERT INTO investigation_notes(alert_id, note, action, actor) VALUES (?, ?, ?, ?)",
                    (alert_id, note, status, actor),
                )
        self.record_audit(alert_id, f"Investigation status updated to {status}", actor=actor, details=note or f"Alert status transitioned to {status}")
        return True

    def get_investigation_notes(self, alert_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_notes WHERE alert_id = ? ORDER BY created_at ASC",
                (alert_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Audit Trail
    # -------------------------------------------------------------------------
    def record_audit(
        self,
        alert_id: Optional[str],
        action: str,
        actor: str = "merchant_operator",
        details: Optional[str] = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO audit_events(alert_id, action, actor, details, occurred_at) VALUES (?, ?, ?, ?, ?)",
                (alert_id, action, actor, details, _iso_now()),
            )

    def list_audit_events(self, alert_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            if alert_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE alert_id = ? ORDER BY occurred_at DESC, id DESC LIMIT ?",
                    (alert_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY occurred_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_serialize_audit_event(dict(r)) for r in rows]

    def audit_history(self, alert_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            if alert_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE alert_id = ? ORDER BY occurred_at ASC, id ASC LIMIT ?",
                    (alert_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY occurred_at ASC, id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_serialize_audit_event(dict(r)) for r in rows]

    # -------------------------------------------------------------------------
    # Notification Recipients & History
    # -------------------------------------------------------------------------
    def list_recipients(self, enabled_only: bool = False) -> list[dict]:
        query = "SELECT * FROM notification_recipients" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY name ASC"
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def recipients(self, enabled_only: bool = False) -> list[dict]:
        return self.list_recipients(enabled_only=enabled_only)

    def save_recipient(
        self,
        name: str,
        email: str,
        role: str,
        enabled: bool = True,
        actor: str = "Merchant Admin",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO notification_recipients(name, email, role, enabled, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(email) DO UPDATE SET
                       name = excluded.name,
                       role = excluded.role,
                       enabled = excluded.enabled,
                       updated_at = CURRENT_TIMESTAMP""",
                (name.strip(), email.strip().lower(), role.strip(), int(enabled)),
            )
        self.record_audit(None, f"Notification recipient updated: {email} ({role})", actor=actor)

    def delete_recipient(self, recipient_id: int, actor: str = "Merchant Admin") -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT email FROM notification_recipients WHERE id = ?", (recipient_id,)).fetchone()
            if not row:
                return False
            email = row["email"]
            conn.execute("DELETE FROM notification_recipients WHERE id = ?", (recipient_id,))
        self.record_audit(None, f"Notification recipient removed: {email}", actor=actor)
        return True

    def record_notification(self, alert_id: str, result: dict[str, str]) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO notification_history(alert_id, recipient, channel, status, failure_reason)
                   VALUES (?, ?, 'Email', ?, ?)""",
                (
                    alert_id,
                    result.get("recipient", ""),
                    result.get("status", "failed"),
                    result.get("reason", ""),
                ),
            )
        self.record_audit(
            alert_id=alert_id,
            action=f"Notification dispatch: {result.get('status')}",
            actor="Notification Engine",
            details=f"Recipient: {result.get('recipient')} - Reason: {result.get('reason')}",
        )

    def list_notification_history(self, limit: int = 50) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_history ORDER BY sent_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Dashboard & Operational Stats
    # -------------------------------------------------------------------------
    def dashboard_snapshot(self) -> dict:
        with self.connection() as conn:
            counts = conn.execute(
                """SELECT
                    COUNT(t.id) AS total_transactions,
                    COALESCE(SUM(CASE WHEN p.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END), 0) AS total_suspicious,
                    COALESCE(SUM(t.amount), 0) AS total_volume
                   FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id"""
            ).fetchone()

            today_counts = conn.execute(
                """SELECT
                    COUNT(t.id) AS transactions_today,
                    COALESCE(SUM(CASE WHEN p.risk_level IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END), 0) AS suspicious_today
                   FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id
                   WHERE date(t.created_at) = date('now')"""
            ).fetchone()

            active_alerts = conn.execute(
                "SELECT COUNT(*) FROM spike_alerts WHERE status IN ('INVESTIGATING', 'Detected', 'OPEN')"
            ).fetchone()[0]

            confirmed_loss = conn.execute(
                """SELECT COALESCE(SUM(t.amount), 0)
                   FROM transactions t
                   WHERE EXISTS (
                       SELECT 1 FROM spike_alerts a
                       WHERE a.status = 'CONFIRMED_FRAUD'
                         AND a.source = t.source
                         AND strftime('%Y-%m-%dT%H:00:00', t.timestamp) = a.window_start
                   )"""
            ).fetchone()[0]

            potential_exposure = conn.execute(
                "SELECT COALESCE(SUM(potential_exposure), 0) FROM spike_alerts WHERE status IN ('INVESTIGATING', 'Detected', 'OPEN', 'CONFIRMED_FRAUD')"
            ).fetchone()[0]

            false_positives = conn.execute(
                "SELECT COUNT(*) FROM spike_alerts WHERE status = 'FALSE_POSITIVE'"
            ).fetchone()[0]

            recent_alerts = conn.execute(
                "SELECT * FROM spike_alerts ORDER BY detected_at DESC LIMIT 10"
            ).fetchall()

            latest_bucket = conn.execute(
                "SELECT * FROM time_buckets ORDER BY bucket_start DESC LIMIT 1"
            ).fetchone()

        total_tx = int(counts["total_transactions"])
        suspicious_tx = int(counts["total_suspicious"])
        macro_fraud_rate = (suspicious_tx / total_tx) if total_tx > 0 else 0.0
        transactions_today = int(today_counts["transactions_today"])
        suspicious_today = int(today_counts["suspicious_today"])
        fraud_rate_today = (suspicious_today / transactions_today) if transactions_today > 0 else 0.0

        # Calculate historical baseline & active window fraud rate
        baseline = None
        current_fraud_rate = macro_fraud_rate
        if latest_bucket and latest_bucket["baseline_rate"] is not None:
            baseline = float(latest_bucket["baseline_rate"])
        if latest_bucket and latest_bucket["fraud_rate"] is not None:
            current_fraud_rate = float(latest_bucket["fraud_rate"])

        # Determine overall system risk status
        if active_alerts > 0:
            risk_status = "FRAUD SPIKE DETECTED"
            risk_code = "SPIKE"
            if recent_alerts and recent_alerts[0]["status"] in ("INVESTIGATING", "Detected", "OPEN"):
                current_fraud_rate = float(recent_alerts[0]["current_rate"])
        elif current_fraud_rate >= 0.08 or (baseline and current_fraud_rate > baseline * 1.5):
            risk_status = "ELEVATED RISK"
            risk_code = "ELEVATED"
        else:
            risk_status = "PAYMENT ACTIVITY NORMAL"
            risk_code = "NORMAL"

        return {
            "total_transactions": total_tx,
            "transactions_today": transactions_today,
            "suspicious_transactions": suspicious_tx,
            "current_fraud_rate": current_fraud_rate,
            "fraud_rate": fraud_rate_today,
            "historical_baseline": baseline,
            "active_alerts_count": int(active_alerts),
            "potential_exposure": float(potential_exposure),
            "confirmed_exposure": float(confirmed_loss),
            "estimated_unmitigated_loss": float(potential_exposure) * float(self.get_setting("average_loss_rate", "0.60")),
            "false_positive_count": int(false_positives),
            "risk_status": risk_status,
            "risk_code": risk_code,
            "recent_alerts": [dict(r) for r in recent_alerts],
            "latest_bucket": dict(latest_bucket) if latest_bucket else None,
        }

    def clear_simulator_data(self) -> None:
        """Clear only CONTROLLED_TEST transactions and test alerts for a fresh demo."""
        with self.connection() as conn:
            conn.execute("DELETE FROM fraud_predictions WHERE transaction_id IN (SELECT transaction_id FROM transactions WHERE source = 'CONTROLLED_TEST')")
            conn.execute("DELETE FROM transactions WHERE source = 'CONTROLLED_TEST'")
            conn.execute("DELETE FROM time_buckets WHERE source = 'CONTROLLED_TEST'")
            conn.execute("DELETE FROM spike_alerts WHERE source = 'CONTROLLED_TEST'")
        self.record_audit(None, "Controlled simulation stream cleared", actor="Demo Controller")

    def reset_for_demo(self) -> None:
        """Complete database reset for clean demo: clears all transactions, predictions, buckets, alerts, and audit logs."""
        with self.connection() as conn:
            conn.execute("DELETE FROM fraud_predictions")
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM time_buckets")
            conn.execute("DELETE FROM investigation_notes")
            conn.execute("DELETE FROM spike_alerts")
            conn.execute("DELETE FROM audit_events")
            conn.execute("DELETE FROM notification_history")
            conn.execute("DELETE FROM webhook_events")
        self.record_audit(None, "Database reset to clean initial state for demo", actor="Demo Controller")
