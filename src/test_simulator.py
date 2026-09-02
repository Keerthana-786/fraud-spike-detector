"""Clearly labelled controlled simulator that executes through the production transaction pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
import uuid

from src.live_pipeline import process_transaction
from src.live_store import LiveStore


def _transaction(timestamp: datetime, amount: float, method: str, scenario: str, order_id: str) -> dict:
    return {
        "transaction_id": f"SIM-{uuid.uuid4().hex[:14].upper()}",
        "timestamp": timestamp.isoformat(),
        "amount": round(amount, 2),
        "currency": "INR",
        "payment_method": method,
        "status": "captured",
        "order_id": order_id,
        "customer_id": f"CUST_{uuid.uuid4().hex[:6].upper()}",
        "source": "CONTROLLED_TEST",
        "raw_event_id": None,
        "scenario": scenario,
    }


def _process_controlled(transaction: dict, store: LiveStore) -> dict:
    store.save_order(
        transaction["order_id"],
        "USER_001",
        "merchant_checkout",
        transaction["amount"],
        transaction["currency"],
    )
    return process_transaction(transaction, store=store)


def start_test_stream(count: int = 5, store: LiveStore | None = None) -> list[dict]:
    """Generate realistic normal traffic through process_transaction()."""
    store = store or LiveStore()
    store.save_user("USER_001", "Cyrus", "cyrus@test.com", role="Merchant Admin")

    methods = ["card", "upi", "netbanking", "wallet"]
    results = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for i in range(count):
        amt = random.uniform(350.0, 3200.0)
        method = random.choice(methods)
        tx = _transaction(
            now - timedelta(seconds=(count - i) * 15),
            amt,
            method,
            "normal_traffic",
            f"ORD-{uuid.uuid4().hex[:8].upper()}",
        )
        res = _process_controlled(tx, store)
        results.append(res)

    store.record_audit(None, f"Generated {count} normal simulation transactions", actor="Demo Controller")
    return results


def inject_controlled_spike(store: LiveStore | None = None) -> list[dict]:
    """Seed historical baseline then inject a high-risk surge through the exact same pipeline."""
    store = store or LiveStore()
    store.save_user("USER_DEMO_001", "Demo Merchant", "demo@sentinelpay.internal", role="Merchant Admin")
    results = []

    now = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=21, minute=0, second=0, microsecond=0)

    # 1. Historical baseline: 12 completed hourly buckets with normal low-risk activity
    for hour in range(12, 0, -1):
        bucket_time = now - timedelta(hours=hour)
        for i in range(20):
            tx = _transaction(
                bucket_time + timedelta(minutes=45 - i),
                250.0 + i,
                "card",
                "baseline_history",
                f"ORD-BASE-{uuid.uuid4().hex[:8].upper()}",
            )
            results.append(_process_controlled(tx, store))

    # 2. High-risk spike burst in the current hour
    current_time = now + timedelta(minutes=15)
    for i in range(30):
        # Elevated amount on unusual payment channel triggers model high risk (probability > 90%)
        tx = _transaction(
            current_time + timedelta(seconds=i * 20),
            round(random.uniform(3500.0, 8900.0), 2),
            "other",
            "fraud_spike_surge",
            f"ORD-SPIKE-{uuid.uuid4().hex[:8].upper()}",
        )
        results.append(_process_controlled(tx, store))

    store.record_audit(None, "Injected controlled fraud spike simulation", actor="Demo Controller")
    return results


def inject_abuse_ring(store: LiveStore | None = None) -> list[dict]:
    """Inject a coordinated attack ring sharing payment method, tight time proximity, and similar amounts."""
    store = store or LiveStore()
    store.save_user("USER_ADMIN", "System Administrator", "admin@sentinelpay.internal", role="Merchant Admin")
    results = []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target_method = "card"
    base_amount = 7490.00

    # Inject 8 coordinated transactions in rapid succession with slightly jittered amounts
    for i in range(8):
        jittered_amt = round(base_amount + random.uniform(-150.0, 150.0), 2)
        tx = _transaction(
            now - timedelta(seconds=(8 - i) * 35),
            jittered_amt,
            target_method,
            "coordinated_abuse_ring",
            f"ORD-RING-{uuid.uuid4().hex[:8].upper()}",
        )
        res = _process_controlled(tx, store)
        results.append(res)

    # Run graph ring detection over the newly ingested transactions
    from src.abuse_ring import run_abuse_ring_pipeline
    run_abuse_ring_pipeline(store=store, min_ring_size=4)

    store.record_audit(None, "Injected coordinated abuse ring simulation (8 transactions)", actor="Demo Controller")
    return results


def stop_simulation(store: LiveStore | None = None) -> dict:
    """Clear simulation stream."""
    store = store or LiveStore()
    store.clear_simulator_data()
    return {"status": "cleared", "message": "Simulation data cleared successfully"}

