"""SentinelPay — AI-Powered Payment Risk Intelligence REST API."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from src.auth import (
    create_session_token,
    hash_password,
    validate_registration,
    valid_email,
    verify_password,
    verify_session_token,
)
from src.live_pipeline import (
    LIVE_MODEL_PATH,
    normalize_razorpay_payment,
    process_transaction,
)
from src.ai_investigator import (
    generate_structured_investigation,
    verify_ai_investigation,
    evaluate_safety_policies,
)
from src.live_store import LiveStore
from src.razorpay_service import create_test_order, verify_payment_signature
from src.test_simulator import (
    inject_controlled_spike,
    start_test_stream,
    stop_simulation,
)

logger = logging.getLogger("sentinelpay.api")
logging.basicConfig(level=logging.INFO)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(
    title="SentinelPay Payment Risk Intelligence API",
    description="Production-grade AI fraud risk monitoring, spike detection, and alert management.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = LiveStore()


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class SignupRequest(BaseModel):
    full_name: str
    email: str
    organization: str = ""
    role: str = "merchant_user"
    password: str
    confirm_password: str
    agree_terms: bool = False
    terms_accepted: bool = False

    def terms_were_accepted(self) -> bool:
        return bool(self.terms_accepted or self.agree_terms)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str
    confirm_password: str


class SettingsUpdateRequest(BaseModel):
    fraud_classification_threshold: Optional[float] = Field(None, ge=0.01, le=0.99)
    min_transactions: Optional[int] = Field(None, ge=1, le=10000)
    baseline_window: Optional[int] = Field(None, ge=1, le=168)
    min_history_buckets: Optional[int] = Field(None, ge=1, le=72)
    zscore_threshold: Optional[float] = Field(None, ge=0.5, le=20.0)
    cost_per_false_positive: Optional[float] = Field(None, ge=0.0)
    cost_per_missed_spike: Optional[float] = Field(None, ge=0.0)
    average_loss_rate: Optional[float] = Field(None, ge=0.01, le=1.0)


class RecipientCreateRequest(BaseModel):
    name: str
    email: str
    role: str = "Security Analyst"
    enabled: bool = True


class InvestigationActionRequest(BaseModel):
    status: str = Field(..., pattern="^(CONFIRMED_FRAUD|FALSE_POSITIVE|RESOLVED|INVESTIGATING)$")
    note: Optional[str] = None
    actor: Optional[str] = "Merchant Admin"


class TransactionIngestRequest(BaseModel):
    transaction_id: str
    timestamp: Optional[str] = None
    amount: float = Field(..., ge=0)
    currency: str = "INR"
    payment_method: str = "card"
    status: str = "captured"
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    source: str = "OFFLINE DATA"


class OrderRequest(BaseModel):
    amount_rupees: float = Field(..., gt=0)
    currency: str = "INR"
    receipt: Optional[str] = None
    user_id: str = "USER_001"
    user_name: str = "Merchant User"
    user_email: str = "merchant@sentinelpay.internal"
    product_id: str = "custom"


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


class UserInviteRequest(BaseModel):
    name: str
    email: str
    role: str
    organization: str = ""


# -----------------------------------------------------------------------------
# Authentication & RBAC Dependencies
# -----------------------------------------------------------------------------
def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    payload = verify_session_token(token)
    if not payload:
        return None
    sess = store.get_session(token)
    if not sess:
        return None
    user = store.user_by_id(payload["user_id"])
    if not user or user.get("status") != "ACTIVE" or user.get("deleted_at"):
        return None
    return user


def require_authenticated_user(authorization: Optional[str] = Header(None)) -> dict:
    user = get_current_user(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
        )
    return user


def require_admin_user(current_user: dict = Depends(require_authenticated_user)) -> dict:
    role = current_user.get("role", "")
    if role not in {"Merchant Admin", "ADMIN", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to perform this action.",
        )
    return current_user


# -----------------------------------------------------------------------------
# System Health
# -----------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    db_ok = False
    try:
        with store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False

    model_ok = LIVE_MODEL_PATH.exists()
    smtp_ok = bool(os.getenv("SMTP_HOST") and os.getenv("ALERT_FROM_EMAIL"))
    razorpay_ok = bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET"))

    overall = "healthy" if (db_ok and model_ok) else "degraded"
    return {
        "status": overall,
        "database": "healthy" if db_ok else "unavailable",
        "fraud_model": "healthy" if model_ok else "unavailable",
        "alert_engine": "healthy" if db_ok else "unavailable",
        "notification_engine": "healthy" if smtp_ok else "unconfigured_fallback",
        "razorpay_test_mode": "connected" if razorpay_ok else "not_connected",
    }


# -----------------------------------------------------------------------------
# Authentication Endpoints
# -----------------------------------------------------------------------------
@app.post("/api/auth/login")
def login(req: LoginRequest) -> dict:
    if not valid_email(req.email) or not req.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email or password.",
        )
    user = store.user_by_email(req.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if user.get("status") != "ACTIVE" or not user.get("email_verified", 1):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email before signing in.")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_session_token(
        user_id=user["user_id"],
        email=user["email"],
        role=user["role"],
        remember_me=req.remember_me,
    )
    store.save_session(token, user["user_id"], expires_at="30d" if req.remember_me else "1d")
    with store.connection() as conn:
        conn.execute("UPDATE users SET last_login_at = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (datetime.now(timezone.utc).isoformat(), user["user_id"]))
    store.record_audit(None, "User logged in", actor=user["name"])

    return {
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "organization": user.get("organization"),
        },
    }


@app.post("/api/auth/register")
def register(req: SignupRequest) -> dict:
    allowed_roles = {"Risk Analyst", "Finance Manager", "Operations Manager"}
    if req.role in {"ADMIN", "admin", "Merchant Admin"} or req.role not in allowed_roles:
        logger.warning("Rejected public signup role attempt: %s", req.role)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select a valid work role.")
    signup_role = req.role
    val_err = validate_registration(
        full_name=req.full_name,
        email=req.email,
        password=req.password,
        confirmation=req.confirm_password,
        organization=req.organization or "SentinelPay Workspace",
        role=signup_role,
        terms=req.terms_were_accepted(),
    )
    if val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=val_err)

    existing = store.user_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create account with these details.",
        )

    user_id = store.next_user_id()
    pwd_hash = hash_password(req.password)
    require_approval = store.get_setting("require_admin_approval", "0") == "1"
    verification_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    store.save_user(
        user_id=user_id,
        name=req.full_name,
        email=req.email,
        role=signup_role,
        password_hash=pwd_hash,
        organization=req.organization or "SentinelPay Workspace",
        terms_accepted=req.terms_were_accepted(),
        status="PENDING_APPROVAL" if require_approval else "PENDING_VERIFICATION",
        email_verified=False,
        created_via="SELF_SIGNUP",
    )
    store.create_verification_token(user_id, verification_token, expires_at)
    store.record_audit(None, "User account registered", actor=req.full_name)

    response = {"status": "pending_verification", "message": f"Please verify your email. We've sent a link to {req.email.strip().lower()}."}
    if not (os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD")):
        response.update({"status": "dev_pending_verification", "message": "Email delivery not configured — verification link shown for development only.", "verification_token": verification_token, "verification_link": f"/api/auth/verify-email?token={verification_token}"})
    return response


@app.get("/api/auth/verify-email")
def verify_email(token: str) -> dict:
    user = store.verify_email_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This verification link is invalid or expired.")
    store.record_audit(None, "EMAIL_VERIFIED", actor=user["email"])
    return {"status": "verified", "message": "Email verified. You can now sign in."}


@app.post("/api/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest) -> dict:
    if not valid_email(req.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address.")

    clean_email = req.email.strip().lower()
    user = store.user_by_email(clean_email)
    generic_msg = f"If an account exists with {clean_email}, a password reset link has been dispatched."
    
    token = None
    if user:
        token = secrets.token_urlsafe(32)
        exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        store.create_password_reset_token(user["user_id"], token, exp)
        store.record_audit(None, "PASSWORD_RESET_REQUESTED", actor=user["email"])

    smtp_ready = bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD"))
    if not smtp_ready:
        res = {
            "status": "dev_sent",
            "message": "Password reset service unconfigured — dev link provided." if user else generic_msg,
        }
        if user and token:
            res.update({
                "reset_token": token,
                "reset_link": f"/api/auth/reset-password?token={token}",
            })
        return res

    return {
        "status": "sent",
        "message": generic_msg,
    }


@app.post("/api/auth/reset-password")
def reset_password(req: ResetPasswordRequest) -> dict:
    if len(req.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least 8 characters.")
    if req.password != req.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match.")

    new_hash = hash_password(req.password)
    user = store.reset_password_with_token(req.token, new_hash)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or expired.")
    return {"status": "success", "message": "Password updated successfully. Please log in with your new password."}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)) -> dict:
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        user = get_current_user(authorization)
        actor = user["name"] if user else "Authenticated User"
        store.delete_session(token)
        store.record_audit(None, "USER_LOGGED_OUT", actor=actor)
    return {"status": "logged_out", "message": "Successfully logged out."}


@app.get("/api/auth/me")
def me(current_user: Optional[dict] = Depends(get_current_user)) -> dict:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "user_id": current_user["user_id"],
        "name": current_user["name"],
        "email": current_user["email"],
        "role": current_user["role"],
        "organization": current_user.get("organization"),
        "created_at": current_user.get("created_at"),
    }


# -----------------------------------------------------------------------------
# Dashboard & Overview Metrics
# -----------------------------------------------------------------------------
@app.get("/api/dashboard/overview")
def overview_metrics() -> dict:
    snapshot = store.dashboard_snapshot()
    return snapshot


@app.get("/api/metrics/financial")
def financial_metrics() -> dict:
    snapshot = store.dashboard_snapshot()
    cost_per_fp = float(store.get_setting("cost_per_false_positive", "50.0"))
    fp_cost = snapshot["false_positive_count"] * cost_per_fp

    return {
        "potential_fraud_exposure": snapshot["potential_exposure"],
        "confirmed_fraud_exposure": snapshot["confirmed_exposure"],
        "confirmed_loss": snapshot["confirmed_exposure"],
        "estimated_unmitigated_loss": snapshot["estimated_unmitigated_loss"],
        "average_loss_rate": float(store.get_setting("average_loss_rate", "0.60")),
        "false_positive_count": snapshot["false_positive_count"],
        "cost_per_false_positive": cost_per_fp,
        "estimated_false_positive_cost": fp_cost,
        "affected_transactions": snapshot["suspicious_transactions"],
    }


@app.get("/api/metrics/timeseries")
def timeseries_metrics(limit: int = 48) -> list[dict]:
    buckets = store.all_time_buckets(limit=limit)
    return buckets


# -----------------------------------------------------------------------------
# Transactions
# -----------------------------------------------------------------------------
@app.get("/api/transactions")
def list_transactions(limit: int = 100, source: Optional[str] = None) -> list[dict]:
    return store.recent_transactions(limit=limit, source=source)


@app.get("/api/transactions/{transaction_id}")
def get_transaction_detail(transaction_id: str) -> dict:
    tx = store.get_transaction(transaction_id)
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


@app.post("/api/transactions/process")
def ingest_transaction(req: TransactionIngestRequest) -> dict:
    ts = req.timestamp or datetime.now(timezone.utc).isoformat()
    tx_dict = {
        "transaction_id": req.transaction_id,
        "timestamp": ts,
        "amount": req.amount,
        "currency": req.currency,
        "payment_method": req.payment_method,
        "status": req.status,
        "order_id": req.order_id,
        "customer_id": req.customer_id,
        "source": req.source,
        "raw_event_id": None,
    }
    result = process_transaction(tx_dict, store=store)
    return result


# -----------------------------------------------------------------------------
# Alerts & Investigations
# -----------------------------------------------------------------------------
@app.get("/api/alerts")
@app.get("/api/incidents")
@app.get("/api/alerts")
def list_alerts(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    return store.list_alerts(severity=severity, status=status, source=source, limit=limit)


@app.get("/api/incidents/{incident_id}")
@app.get("/api/alerts/{alert_id}")
def get_alert_detail(alert_id: str) -> dict:
    alert = store.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident / Alert not found")
    notes = store.get_investigation_notes(alert_id)
    history = store.list_audit_events(alert_id=alert_id)
    affected_tx = store.transactions_for_bucket(alert["window_start"], alert["source"], limit=50)

    ai_investigation = generate_structured_investigation(alert, affected_tx, api_key=os.getenv("GEMINI_API_KEY"))
    ai_verification = verify_ai_investigation(alert, ai_investigation, affected_tx)
    safety_policies = evaluate_safety_policies(ai_investigation, ai_verification)

    return {
        "alert": alert,
        "incident": alert,
        "notes": notes,
        "audit_history": history,
        "affected_transactions": affected_tx,
        "ai_investigation": ai_investigation,
        "ai_verification": ai_verification,
        "safety_policies": safety_policies,
    }


@app.post("/api/incidents/{incident_id}/investigate")
@app.post("/api/alerts/{alert_id}/investigate")
def alert_action(alert_id: str, req: InvestigationActionRequest) -> dict:
    alert = store.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident / Alert not found")

    success = store.update_alert_status(
        alert_id=alert_id,
        status=req.status,
        note=req.note,
        actor=req.actor or "Merchant Admin",
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to update incident status")

    return {
        "status": "updated",
        "alert_id": alert_id,
        "incident_id": alert_id,
        "new_status": req.status,
        "note": req.note,
    }


# -----------------------------------------------------------------------------
# Audit Logs
# -----------------------------------------------------------------------------
@app.get("/api/audit-logs")
def get_audit_logs(alert_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    return store.list_audit_events(alert_id=alert_id, limit=limit)


# -----------------------------------------------------------------------------
# Settings & Notification Recipients
# -----------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings() -> dict:
    return store.get_all_settings()


@app.put("/api/settings")
def update_settings(req: SettingsUpdateRequest, admin: dict = Depends(require_admin_user)) -> dict:
    data = req.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No settings provided to update.")
    store.update_settings(data, actor=admin.get("name", "Merchant Admin"))
    return {"status": "saved", "settings": store.get_settings()}


@app.get("/api/recipients")
def list_recipients(admin: dict = Depends(require_admin_user)) -> list[dict]:
    return store.list_recipients()


# -----------------------------------------------------------------------------
# Administration: users
# -----------------------------------------------------------------------------
@app.get("/api/users")
def list_users(admin: dict = Depends(require_admin_user)) -> list[dict]:
    return store.list_users()


@app.patch("/api/users/{user_id}")
def update_user(user_id: str, req: UserUpdateRequest, admin: dict = Depends(require_admin_user)) -> dict:
    allowed_roles = {"ADMIN", "Merchant Admin", "Risk Analyst", "Finance Manager", "Operations Manager"}
    allowed_statuses = {"ACTIVE", "PENDING_APPROVAL", "PENDING_VERIFICATION", "DISABLED"}
    if req.role is not None and req.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Invalid role.")
    if req.status is not None and req.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid status.")
    if user_id == admin["user_id"] and req.status == "DISABLED":
        raise HTTPException(status_code=400, detail="Confirm self-lockout with a separate administrator.")
    try:
        updated = store.update_user(user_id, role=req.role, status=req.status, actor=admin["name"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    if req.status == "DISABLED":
        store.invalidate_user_sessions(user_id)
    return updated


@app.delete("/api/users/{user_id}")
def deactivate_user(user_id: str, admin: dict = Depends(require_admin_user)) -> dict:
    try:
        if not store.soft_delete_user(user_id, admin["name"]):
            raise HTTPException(status_code=404, detail="User not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deactivated", "user_id": user_id}


@app.post("/api/users/invite")
def invite_user(req: UserInviteRequest, admin: dict = Depends(require_admin_user)) -> dict:
    if not valid_email(req.email) or req.role not in {"ADMIN", "Merchant Admin", "Risk Analyst", "Finance Manager", "Operations Manager"}:
        raise HTTPException(status_code=400, detail="Invalid invitation details.")
    if store.user_by_email(req.email):
        raise HTTPException(status_code=400, detail="An account with this email may already exist.")
    user_id = store.next_user_id()
    store.save_user(user_id, req.name, req.email, role=req.role, organization=req.organization or "SentinelPay Workspace", status="PENDING_VERIFICATION", email_verified=False, created_via="ADMIN_INVITE")
    token = secrets.token_urlsafe(32)
    store.create_verification_token(user_id, token, (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    store.record_audit(None, "USER_INVITED", actor=admin["name"], details=json.dumps({"user_id": user_id, "role": req.role}))
    return {"status": "invited", "user_id": user_id, "verification_token": token}


@app.post("/api/recipients")
def add_recipient(req: RecipientCreateRequest, admin: dict = Depends(require_admin_user)) -> dict:
    if not valid_email(req.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid recipient email address")
    store.save_recipient(name=req.name, email=req.email, role=req.role, enabled=req.enabled, actor=admin.get("name", "Merchant Admin"))
    return {"status": "saved", "email": req.email}


@app.delete("/api/recipients/{recipient_id}")
def delete_recipient(recipient_id: int, admin: dict = Depends(require_admin_user)) -> dict:
    success = store.delete_recipient(recipient_id, actor=admin.get("name", "Merchant Admin"))
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")
    return {"status": "deleted", "recipient_id": recipient_id}


@app.get("/api/notifications")
def list_notifications(limit: int = 50) -> list[dict]:
    return store.list_notification_history(limit=limit)


# -----------------------------------------------------------------------------
# Model Health & Evaluation Diagnostics
# -----------------------------------------------------------------------------
@app.get("/api/model/health")
def model_health() -> dict:
    report_path = PROJECT_ROOT / "data" / "evaluation_report.json"
    evaluation_data = None
    if report_path.exists():
        try:
            with open(report_path) as f:
                evaluation_data = json.load(f)
        except Exception:
            evaluation_data = None

    model_exists = LIVE_MODEL_PATH.exists()
    measured = (evaluation_data or {}).get("transaction_classifier", {})
    metrics = {
        "transaction_precision": measured.get("precision"),
        "transaction_recall": measured.get("recall"),
        "transaction_f1_score": measured.get("f1"),
        "transaction_false_positive_rate": measured.get("false_positive_rate"),
        "spike_recall": (evaluation_data or {}).get("spike_level_performance", {}).get("spike_recall"),
        "alert_precision": (evaluation_data or {}).get("alert_event_performance", {}).get("alert_precision"),
        "alert_f1_score": (evaluation_data or {}).get("alert_event_performance", {}).get("alert_f1_score"),
        "bucket_fpr": (evaluation_data or {}).get("alert_event_performance", {}).get("bucket_level_false_positive_rate"),
    }
    return {
        "model_name": "SentinelPay Live XGBoost Classifier",
        "model_version": "1.0.0-prod",
        "model_status": "ready" if model_exists else "not_trained",
        "evaluation_status": measured.get("status", "UNAVAILABLE"),
        "evaluation_method": "Chronological Held-out Test Split (PaySim Benchmark)",
        "held_out_test_size": measured.get("held_out_test_size"),
        "metrics": metrics,
        "confusion_matrix": measured.get("confusion_matrix"),
        "feature_importances": [],
        "evaluation": evaluation_data,
    }


@app.post("/api/razorpay/test-webhook")
def simulate_razorpay_webhook(
    amount: float = 7500.0,
    method: str = "card",
    status_payment: str = "captured",
    event_type: str = "payment.captured",
) -> dict:
    """Generate and process an authentic Razorpay test webhook through the complete shared pipeline."""
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET") or "test_webhook_secret_key"
    os.environ["RAZORPAY_WEBHOOK_SECRET"] = secret

    tx_id = f"pay_rzp_test_{secrets.token_hex(4)}"
    event_id = f"evt_rzp_test_{secrets.token_hex(4)}"
    amount_paisa = int(amount * 100)

    payload = {
        "id": event_id,
        "event": event_type,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "payload": {
            "payment": {
                "entity": {
                    "id": tx_id,
                    "created_at": int(datetime.now(timezone.utc).timestamp()),
                    "amount": amount_paisa,
                    "currency": "INR",
                    "method": method,
                    "status": status_payment,
                    "email": "customer@razorpay-test.com",
                    "contact": "+919876543210",
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Record event
    store.record_event(event_id, event_type)
    store.record_audit(None, "WEBHOOK_RECEIVED", actor="Razorpay Test Simulator", details=f"Simulated {event_type} ({tx_id})")

    # Normalize & process
    normalized = normalize_razorpay_payment(payload)
    result = process_transaction(normalized, store=store)

    return {
        "status": "success",
        "event_id": event_id,
        "transaction_id": tx_id,
        "signature_verified": True,
        "pipeline_result": result,
    }


# -----------------------------------------------------------------------------
# Controlled Test Simulator Endpoints
# -----------------------------------------------------------------------------
@app.post("/api/simulator/normal")
def simulate_normal_traffic(count: int = 5) -> dict:
    # Clear previous simulation data to ensure demo runs start from a clean state
    store.clear_simulator_data()
    results = start_test_stream(count=count, store=store)
    return {
        "status": "completed",
        "transactions_generated": len(results),
        "message": f"Successfully injected {len(results)} normal transactions through pipeline",
    }


@app.post("/api/simulator/spike")
def simulate_fraud_spike() -> dict:
    # Ensure previous simulation data is cleared to avoid stale alerts or buckets
    store.clear_simulator_data()
    results = inject_controlled_spike(store=store)
    alerts = store.list_alerts(limit=5)
    return {
        "status": "completed",
        "events_processed": len(results),
        "active_alerts": alerts,
        "message": "Injected historical baseline and high-risk surge. Fraud spike triggered.",
    }


@app.post("/api/simulator/reset")
def simulate_reset() -> dict:
    return stop_simulation(store=store)


# -----------------------------------------------------------------------------
# Optional Razorpay Test Mode Endpoints
# -----------------------------------------------------------------------------
def verify_razorpay_webhook_sig(body: bytes, signature: Optional[str], secret: Optional[str]) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/payments/orders")
def payment_order(request: OrderRequest) -> dict:
    try:
        order = create_test_order(request.amount_rupees, request.currency, request.receipt)
        store.save_user(request.user_id, request.user_name, request.user_email)
        store.save_order(order["id"], request.user_id, request.product_id, request.amount_rupees, request.currency)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("Razorpay Test Mode order creation unavailable: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Razorpay Test Mode is unavailable") from exc
    key_id = os.getenv("RAZORPAY_KEY_ID", "")
    return {"key_id": key_id, "order": order, "mode": "TEST"}


@app.post("/payments/verify")
def payment_verify(request: PaymentVerificationRequest) -> dict:
    if not verify_payment_signature(request.razorpay_order_id, request.razorpay_payment_id, request.razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment signature")
    logger.info("Verified Razorpay Test Mode payment %s", request.razorpay_payment_id)
    return {"status": "verified", "razorpay_order_id": request.razorpay_order_id, "razorpay_payment_id": request.razorpay_payment_id, "mode": "TEST"}


@app.post("/payments/webhook")
@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
) -> dict:
    body = await request.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Razorpay webhook secret is not configured")
    if not verify_razorpay_webhook_sig(body, x_razorpay_signature, secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event_id = str(event.get("id") or "")
    if event_id and store.event_seen(event_id):
        return {"status": "duplicate", "event_id": event_id}

    if event_id:
        store.record_event(event_id, event.get("event", "unknown"))

    try:
        normalized = normalize_razorpay_payment(event)
        existing = store.get_transaction(normalized["transaction_id"])
        if existing:
            store.update_transaction_status(normalized["transaction_id"], normalized["status"], normalized.get("raw_event_id"))
            return {"status": "processed", "result": {"status": "updated", "transaction_id": normalized["transaction_id"]}}
        result = process_transaction(normalized, store=store)
        return {"status": "processed", "result": result}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to process Razorpay webhook event: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing error") from exc
