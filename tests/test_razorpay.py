import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import api.main as main
from src.live_store import LiveStore
from src.notifications import send_alert_email
from src.test_simulator import start_test_stream
from src.auth import hash_password, validate_registration, verify_password


def _payload(event_id="evt_test_1", payment_id="pay_test_1", status="captured"):
    return {
        "id": event_id,
        "event": "payment." + status,
        "payload": {"payment": {"entity": {
            "id": payment_id,
            "created_at": 1724400000,
            "amount": 12500,
            "currency": "INR",
            "method": "upi",
            "status": status,
        }}},
    }


def _signed(payload, secret="test-webhook-secret"):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, signature


def test_valid_webhook_persists_and_duplicate_is_idempotent(monkeypatch, tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test-webhook-secret")
    client = TestClient(main.app)
    body, signature = _signed(_payload())

    first = client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": signature})
    duplicate = client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": signature})

    assert first.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert len(store.recent_transactions()) == 1


def test_lifecycle_event_updates_status_without_duplicate_transaction(monkeypatch, tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test-webhook-secret")
    client = TestClient(main.app)
    body, signature = _signed(_payload(status="authorized"))
    assert client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": signature}).status_code == 200
    body, signature = _signed(_payload(event_id="evt_test_2", status="captured"))
    assert client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": signature}).status_code == 200
    assert store.recent_transactions()[0]["status"] == "captured"
    assert len(store.recent_transactions()) == 1


def test_invalid_signature_and_malformed_payload_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "store", LiveStore(tmp_path / "live.sqlite3"))
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test-webhook-secret")
    client = TestClient(main.app)
    body, _ = _signed(_payload())
    assert client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": "bad"}).status_code == 401
    malformed, signature = _signed({"id": "evt_bad", "event": "payment.captured"})
    assert client.post("/webhooks/razorpay", content=malformed, headers={"x-razorpay-signature": signature}).status_code == 400


def test_alert_audit_and_notification_failure_are_persisted_without_blocking(tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    alert = {"alert_id": "LIVE-AUDIT", "severity": "HIGH", "detected_at": "now", "current_rate": 0.4, "baseline_rate": 0.1, "affected_transactions": 4, "potential_exposure": 100}
    store.create_alert({**alert, "window_start": "now", "window_end": "now", "source": "RAZORPAY_TEST", "multiplier": 4, "anomaly_score": 4, "status": "Detected", "root_cause_json": "[]"})
    store.save_recipient("Security", "security@example.com", "Security Lead")
    results = send_alert_email(alert, store.recipients(enabled_only=True))
    for result in results:
        store.record_notification(alert["alert_id"], result)
    assert store.audit_history("LIVE-AUDIT")[0]["action"] == "Alert created"
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_history").fetchone()[0] == 1


def test_order_creation_links_order_to_application_user(monkeypatch, tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "create_test_order", lambda amount, currency, receipt: {"id": "order_linked", "amount": 99900, "currency": currency, "status": "created"})
    client = TestClient(main.app)
    response = client.post("/payments/orders", json={"amount_rupees": 999, "currency": "INR", "user_id": "USER_001", "user_name": "Cyrus", "user_email": "cyrus@test.com", "product_id": "premium"})
    assert response.status_code == 200
    assert store.order_user("order_linked")["name"] == "Cyrus"


def test_controlled_stream_is_linked_to_cyrus_and_labelled(tmp_path, monkeypatch):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr("src.test_simulator.LiveStore", lambda: store)
    result = start_test_stream(1)
    assert result[0]["status"] == "processed"
    row = store.recent_transactions(1)[0]
    assert row["source"] == "CONTROLLED_TEST"
    assert store.order_user(row["order_id"])["name"] == "Cyrus"


def test_passwords_are_hashed_and_registration_validation_is_strict():
    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)
    assert validate_registration("Cyrus", "bad-email", "short", "short", "Acme", "Merchant Admin", True)
    assert validate_registration("Cyrus", "cyrus@example.com", "long-enough", "different", "Acme", "Merchant Admin", True) == "Passwords do not match."
    assert validate_registration("Cyrus", "cyrus@example.com", "long-enough", "long-enough", "Acme", "Merchant Admin", True) is None


def test_registered_user_can_be_loaded_for_secure_login(tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    store.save_user("USER_001", "Cyrus", "cyrus@example.com", "customer", hash_password("correct horse battery staple"), "Acme", True)
    user = store.user_by_email("CYRUS@EXAMPLE.COM")
    assert user["password_hash"] != "correct horse battery staple"
    assert verify_password("correct horse battery staple", user["password_hash"])
    assert not verify_password("wrong", user["password_hash"])