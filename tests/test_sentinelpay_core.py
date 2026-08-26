"""Comprehensive production test suite for SentinelPay Payment Risk Intelligence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

import api.main as main
from src.auth import (
    create_session_token,
    hash_password,
    validate_registration,
    valid_email,
    verify_password,
    verify_session_token,
)
from src.live_pipeline import process_transaction
from src.live_store import LiveStore
from src.test_simulator import (
    inject_controlled_spike,
    start_test_stream,
    stop_simulation,
)


@pytest.fixture
def temp_store(tmp_path):
    db_path = tmp_path / "sentinelpay_test.sqlite3"
    return LiveStore(db_path)


# =============================================================================
# 1. Authentication & Security Tests
# =============================================================================
def test_password_hashing_and_verification():
    raw = "SuperSecretPassword123!"
    encoded = hash_password(raw)

    assert encoded.startswith("pbkdf2_sha256$")
    assert encoded != raw
    assert verify_password(raw, encoded)
    assert not verify_password("WrongPassword123!", encoded)
    assert not verify_password("", encoded)


def test_registration_validation_rules():
    # Missing full name
    assert validate_registration("", "test@merchant.com", "pass12345", "pass12345", "Merchant Org", "Merchant Admin", True) == "Please enter your full name."
    # Invalid email
    assert validate_registration("Alex", "not-an-email", "pass12345", "pass12345", "Merchant Org", "Merchant Admin", True) == "Enter a valid email address."
    # Short password
    assert validate_registration("Alex", "test@merchant.com", "short", "short", "Merchant Org", "Merchant Admin", True) == "Password must contain at least 8 characters."
    # Mismatched password
    assert validate_registration("Alex", "test@merchant.com", "pass12345", "different", "Merchant Org", "Merchant Admin", True) == "Passwords do not match."
    # Missing org
    assert validate_registration("Alex", "test@merchant.com", "pass12345", "pass12345", "", "Merchant Admin", True) == "Please enter your organization name."
    # Terms not accepted
    assert validate_registration("Alex", "test@merchant.com", "pass12345", "pass12345", "Merchant Org", "Merchant Admin", False) == "Accept the Terms and Privacy Policy to continue."
    # Valid
    assert validate_registration("Alex", "test@merchant.com", "pass12345", "pass12345", "Merchant Org", "Merchant Admin", True) is None


def test_session_token_and_remember_me():
    token_normal = create_session_token("USER_001", "alex@merchant.com", "Merchant Admin", remember_me=False)
    payload = verify_session_token(token_normal)
    assert payload is not None
    assert payload["user_id"] == "USER_001"
    assert payload["email"] == "alex@merchant.com"
    assert payload["remember_me"] is False

    token_remember = create_session_token("USER_002", "sarah@merchant.com", "Security Analyst", remember_me=True)
    payload_rem = verify_session_token(token_remember)
    assert payload_rem is not None
    assert payload_rem["remember_me"] is True

    # Tampered token
    assert verify_session_token("invalid.tampered.token") is None
    assert verify_session_token("") is None


# =============================================================================
# 2. Transaction Processing & Idempotency Tests
# =============================================================================
def test_transaction_processing_and_idempotency(temp_store):
    tx = {
        "transaction_id": "TX_TEST_001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": 1500.0,
        "currency": "INR",
        "payment_method": "card",
        "status": "captured",
        "order_id": "ORD_001",
        "customer_id": "CUST_001",
        "source": "OFFLINE DATA",
        "raw_event_id": None,
    }

    first = process_transaction(tx, store=temp_store)
    assert first["status"] == "processed"
    assert first["transaction_id"] == "TX_TEST_001"
    assert first["prediction"]["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    # Duplicate should return duplicate status without inserting second row
    duplicate = process_transaction(tx, store=temp_store)
    assert duplicate["status"] == "duplicate"
    assert len(temp_store.recent_transactions()) == 1


def test_transaction_validation_errors(temp_store):
    # Missing fields
    with pytest.raises(ValueError, match="missing required fields"):
        process_transaction({"transaction_id": "BAD"}, store=temp_store)

    # Negative amount
    with pytest.raises(ValueError, match="cannot be negative"):
        process_transaction({
            "transaction_id": "TX_NEG",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "amount": -50.0,
            "currency": "INR",
            "payment_method": "card",
            "status": "captured",
            "source": "TEST",
        }, store=temp_store)


# =============================================================================
# 3. Spike Detection Engine & Alert Lifecycle Tests
# =============================================================================
def test_spike_detection_and_alert_generation(temp_store):
    now = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=21, minute=0, second=0, microsecond=0)

    # 1. Feed 12 hourly baseline buckets with normal transactions (low rate)
    for hour in range(12, 0, -1):
        bucket_time = now - timedelta(hours=hour)
        for i in range(20):
            tx = {
                "transaction_id": f"BASE_TX_{hour}_{i}",
                "timestamp": (bucket_time + timedelta(minutes=45 - i)).isoformat(),
                "amount": 250.0 + i,
                "currency": "INR",
                "payment_method": "card",
                "status": "captured",
                "source": "CONTROLLED_TEST",
                "raw_event_id": None,
            }
            res = process_transaction(tx, store=temp_store)
            assert res["alert"] is None  # Normal traffic should NOT trigger alert

    # 2. Inject surge of high-risk transactions in the current hour
    current_time = now + timedelta(minutes=10)
    alerts_triggered = []
    for i in range(30):
        tx = {
            "transaction_id": f"SURGE_TX_{i}",
            "timestamp": (current_time + timedelta(minutes=i)).isoformat(),
            "amount": 10000000.0 + i * 5000,
            "currency": "INR",
            "payment_method": "other",
            "status": "captured",
            "source": "CONTROLLED_TEST",
            "raw_event_id": None,
        }
        res = process_transaction(tx, store=temp_store)
        if res.get("alert"):
            alerts_triggered.append(res["alert"])

    assert len(alerts_triggered) > 0
    created_alert = alerts_triggered[-1]
    assert created_alert["severity"] in {"HIGH", "CRITICAL"}
    assert created_alert["affected_transactions"] >= 3

    # Check alert persistence in DB
    alerts = temp_store.list_alerts()
    assert len(alerts) >= 1
    assert alerts[0]["status"] == "INVESTIGATING"


def test_alert_investigation_workflow_and_audit(temp_store):
    # Create an alert
    alert = {
        "alert_id": "ALERT-INV-TEST",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "window_start": "2026-08-24T08:00:00",
        "window_end": "2026-08-24T08:00:00",
        "source": "CONTROLLED_TEST",
        "baseline_rate": 0.02,
        "current_rate": 0.35,
        "multiplier": 17.5,
        "anomaly_score": 5.4,
        "severity": "HIGH",
        "status": "INVESTIGATING",
        "affected_transactions": 14,
        "potential_exposure": 85000.0,
        "root_cause_json": json.dumps([{"feature": "Transaction Amount", "contribution": 0.45}]),
    }
    temp_store.create_alert(alert, actor="Test Alert Engine")

    # 1. Update status to CONFIRMED_FRAUD with note
    temp_store.update_alert_status(
        "ALERT-INV-TEST",
        status="CONFIRMED_FRAUD",
        note="Verified carding attack patterns.",
        actor="Security Lead",
    )
    loaded = temp_store.get_alert("ALERT-INV-TEST")
    assert loaded["status"] == "CONFIRMED_FRAUD"

    # Verify audit logs
    audit = temp_store.list_audit_events(alert_id="ALERT-INV-TEST")
    assert len(audit) >= 2
    assert any("CONFIRMED_FRAUD" in a["action"] for a in audit)

    # 2. Mark false positive
    temp_store.update_alert_status(
        "ALERT-INV-TEST",
        status="FALSE_POSITIVE",
        note="Legitimate promotional marketing flash sale.",
        actor="Merchant Admin",
    )
    loaded_fp = temp_store.get_alert("ALERT-INV-TEST")
    assert loaded_fp["status"] == "FALSE_POSITIVE"


# =============================================================================
# 4. Settings & Notification Recipients Tests
# =============================================================================
def test_system_settings_and_notification_recipients(temp_store):
    # Check default setting
    default_z = temp_store.get_setting("zscore_threshold")
    assert float(default_z) == 3.0

    # Update settings
    temp_store.update_settings({"zscore_threshold": "4.5", "cost_per_false_positive": "75.0"}, actor="Admin")
    assert float(temp_store.get_setting("zscore_threshold")) == 4.5
    assert float(temp_store.get_setting("cost_per_false_positive")) == 75.0

    # Recipients CRUD
    temp_store.save_recipient("Alice Security", "alice@merchant.com", "Security Analyst", enabled=True)
    recipients = temp_store.list_recipients()
    assert len(recipients) == 1
    assert recipients[0]["email"] == "alice@merchant.com"

    # Delete recipient
    temp_store.delete_recipient(recipients[0]["id"])
    assert len(temp_store.list_recipients()) == 0


# =============================================================================
# 5. REST API Integration Tests
# =============================================================================
def test_rest_api_endpoints(monkeypatch, temp_store):
    monkeypatch.setattr(main, "store", temp_store)
    client = TestClient(main.app)

    # 1. Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] in {"healthy", "degraded"}

    # 2. User registration & login
    reg_payload = {
        "full_name": "Merchant Owner",
        "email": "owner@sentinelpay.test",
        "organization": "Sentinel Commerce",
        "role": "Risk Analyst",
        "password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!",
        "agree_terms": True,
    }
    res_reg = client.post("/api/auth/register", json=reg_payload)
    assert res_reg.status_code == 200
    vtoken = res_reg.json().get("verification_token")
    if vtoken:
        res_ver = client.get(f"/api/auth/verify-email?token={vtoken}")
        assert res_ver.status_code == 200

    login_res = client.post("/api/auth/login", json={"email": "owner@sentinelpay.test", "password": "SecurePassword123!"})
    assert login_res.status_code == 200
    assert login_res.json()["user"]["role"] == "Risk Analyst"
    token = login_res.json()["token"]
    assert token is not None

    # 3. Overview metrics
    res_ov = client.get("/api/dashboard/overview")
    assert res_ov.status_code == 200
    assert "risk_status" in res_ov.json()
    assert "total_transactions" in res_ov.json()
    assert "transactions_today" in res_ov.json()
    assert "fraud_rate" in res_ov.json()
    assert res_ov.json()["transactions_today"] >= 0
    assert 0 <= res_ov.json()["fraud_rate"] <= 1

    # 4. Financial metrics
    res_fin = client.get("/api/metrics/financial")
    assert res_fin.status_code == 200
    assert "estimated_false_positive_cost" in res_fin.json()

    # 5. Simulator endpoints
    res_sim_norm = client.post("/api/simulator/normal?count=3")
    assert res_sim_norm.status_code == 200
    assert res_sim_norm.json()["transactions_generated"] == 3

    res_sim_reset = client.post("/api/simulator/reset")
    assert res_sim_reset.status_code == 200
