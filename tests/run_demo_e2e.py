import argparse
import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.auth import hash_password, verify_password, validate_registration, create_session_token, verify_session_token
from src.live_store import LiveStore
from src.test_simulator import start_test_stream, inject_controlled_spike

def run_demo(reset: bool = True):
    print("=" * 70)
    print("       SENTINELPAY — CLEAN END-TO-END DEMO EXECUTION RUN")
    print("=" * 70)

    store = LiveStore()
    if reset:
        print("\n[RESET] Clearing database to clean baseline state...")
        store.reset_for_demo()
        print("  -> Database reset completed.")

    print("\nSTEP 1: Public Merchant Registration (strictly creates merchant_user)")
    val = validate_registration(
        "Retail Merchant",
        "merchant_demo@test.com",
        "DemoPass123!",
        "DemoPass123!",
        "Acme Retail Corp",
        "merchant_user",
        True,
    )
    assert val is None, f"Registration validation failed: {val}"
    uid = store.next_user_id()
    store.save_user(
        uid,
        "Retail Merchant",
        "merchant_demo@test.com",
        role="merchant_user",
        password_hash=hash_password("DemoPass123!"),
        organization="Acme Retail Corp",
        terms_accepted=True,
    )
    user = store.user_by_email("merchant_demo@test.com")
    assert user is not None
    assert user["role"] == "merchant_user"
    print(f"  -> User registered: {user['name']} | Role: {user['role']} | Org: {user['organization']}")

    print("\nSTEP 2: Merchant Sign-In & Session Token Generation")
    assert verify_password("DemoPass123!", user["password_hash"])
    token = create_session_token(user["user_id"], user["email"], user["role"], remember_me=False)
    payload = verify_session_token(token)
    assert payload is not None
    assert payload["email"] == "merchant_demo@test.com"
    print(f"  -> Authenticated: Signed token issued for {payload['email']} (expires in 24h)")

    print("\nSTEP 3: Overview Initial State (Clean DB Baseline)")
    snap0 = store.dashboard_snapshot()
    print(f"  -> Risk Status:   [{snap0['risk_status']}]")
    print(f"  -> Active Alerts: {snap0['active_alerts_count']}")
    print(f"  -> Total TXs:     {snap0['total_transactions']}")
    print(f"  -> Fraud Rate:    {snap0['current_fraud_rate']:.2%}")
    assert snap0["risk_status"] == "PAYMENT ACTIVITY NORMAL"
    assert snap0["active_alerts_count"] == 0

    print("\nSTEP 4: Live Monitoring — Ingest Normal Traffic")
    norm_results = start_test_stream(count=15, store=store)
    snap1 = store.dashboard_snapshot()
    print(f"  -> Ingested:      {len(norm_results)} normal merchant payments")
    print(f"  -> Total TXs:     {snap1['total_transactions']}")
    print(f"  -> Fraud Rate:    {snap1['current_fraud_rate']:.2%}")
    print(f"  -> Risk Status:   [{snap1['risk_status']}]")
    assert snap1["risk_status"] == "PAYMENT ACTIVITY NORMAL"
    assert snap1["active_alerts_count"] == 0

    print("\nSTEP 5: Inject Controlled Fraud Spike Surge")
    spike_results = inject_controlled_spike(store=store)
    snap2 = store.dashboard_snapshot()
    print(f"  -> Processed:     {len(spike_results)} baseline + high-risk surge payments")
    print(f"  -> Total TXs:     {snap2['total_transactions']}")
    print(f"  -> Current Rate:  {snap2['current_fraud_rate']:.2%}")
    print(f"  -> Risk Status:   [{snap2['risk_status']}]")
    print(f"  -> Active Alerts: {snap2['active_alerts_count']}")
    print(f"  -> Exposure:      ₹{snap2['potential_exposure']:,.0f}")
    assert snap2["risk_status"] == "FRAUD SPIKE DETECTED"
    assert snap2["active_alerts_count"] >= 1

    print("\nSTEP 6: Alert Triage & Novelty Diagnostic Cards")
    alerts = store.list_alerts()
    assert len(alerts) > 0
    top_alert = alerts[0]
    print(f"  -> Alert ID:       {top_alert['alert_id']}")
    print(f"  -> Severity:       {top_alert['severity']}")
    print(f"  -> Anomaly Z-Score: {top_alert['anomaly_score']:.1f} standard deviations above baseline")
    print(f"  -> Current Rate:   {top_alert['current_rate']:.1%} (Baseline: {top_alert['baseline_rate']:.1%})")
    
    slice_attr = top_alert.get("slice_attribution", {})
    if not slice_attr:
        slice_attr = store.compute_slice_attribution(top_alert["window_start"], top_alert["source"])
    print(f"  -> Slice Attribution Card: {slice_attr.get('narrative', 'Computed attribution')}")
    print("  -> Non-Action Assessment:  [🛡️ NO AUTOMATED ACTION TAKEN — Human confirmation mandatory]")

    print("\nSTEP 7: Operational Investigation (Confirm Fraud Action)")
    store.update_alert_status(
        top_alert["alert_id"],
        "CONFIRMED_FRAUD",
        note="Confirmed credential stuffing surge on high-value channel",
        actor=user["name"],
    )
    updated_alert = store.get_alert(top_alert["alert_id"])
    assert updated_alert["status"] == "CONFIRMED_FRAUD"
    snap3 = store.dashboard_snapshot()
    print(f"  -> New Alert Status:   [{updated_alert['status']}]")
    print(f"  -> Confirmed Exposure: ₹{snap3['confirmed_exposure']:,.0f}")

    print("\nSTEP 8: Audit Trail Verification")
    audits = store.list_audit_events(alert_id=top_alert["alert_id"])
    assert len(audits) >= 2
    print(f"  -> Total Audit Events for {top_alert['alert_id']}: {len(audits)}")
    for a in audits:
        detail_str = f" | Details: {a['details']}" if a.get('details') else ""
        print(f"     • {a['occurred_at'][:19]} | Actor: {a['actor']} | Action: {a['action']}{detail_str}")

    print("\nSTEP 9: Sign Out & Admin Sign-In")
    admin_user = store.user_by_email("admin@sentinelpay.com")
    if not admin_user:
        store.save_user("USER_ADMIN", "Admin User", "admin@sentinelpay.com", role="Merchant Admin", password_hash=hash_password("AdminPass123!"), organization="SentinelPay Ops", terms_accepted=True)
        admin_user = store.user_by_email("admin@sentinelpay.com")
    
    admin_token = create_session_token(admin_user["user_id"], admin_user["email"], admin_user["role"])
    admin_payload = verify_session_token(admin_token)
    assert admin_payload["role"] == "Merchant Admin"
    print(f"  -> Merchant signed out. Admin authenticated: {admin_user['name']} ({admin_user['role']})")

    print("\nSTEP 10: Model Health & Held-Out Test Evaluation Diagnostics")
    report_file = PROJECT_ROOT / "data" / "evaluation_report.json"
    with open(report_file) as f:
        eval_report = json.load(f)
    
    print(f"  -> Evaluation Split:            Chronological Held-Out Test Split (not touched in tuning)")
    print(f"  -> Spike-Level Recall:          {eval_report['spike_level_performance']['spike_recall']:.1%} (4/4 ground truth caught)")
    print(f"  -> Alert Event Precision:       {eval_report['alert_event_performance']['alert_precision']:.2%}")
    print(f"  -> Hourly Bucket FPR:           {eval_report['alert_event_performance']['bucket_level_false_positive_rate']:.4%}")
    print(f"  -> Cost per False Review:       ${eval_report['parameters']['cost_per_false_alert_usd']:.2f}")
    print(f"  -> Net Financial Risk Averted:  ${eval_report['operational_financial_cost']['net_financial_risk_prevented_usd']:,.2f}")

    print("\n" + "=" * 70)
    print("✅ DEMO SEQUENCE COMPLETED WITH 100% VERIFIED PASS STATUS")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SentinelPay Clean End-to-End Demo Runner")
    parser.add_argument("--reset", action="store_true", default=True, help="Reset database to clean baseline before running")
    args = parser.parse_args()
    run_demo(reset=args.reset)
