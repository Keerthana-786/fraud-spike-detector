import json
from datetime import datetime, timezone, timedelta

import pytest

from src.live_store import LiveStore
import src.live_pipeline as lp


class FakeModel:
    def __init__(self, prob=0.5, risk='LOW'):
        self.prob = prob
        self.risk = risk

    def predict(self, transaction, threshold=0.5):
        return {
            'fraud_probability': float(self.prob),
            'risk_level': self.risk,
            'model_status': 'scored',
            'explanation': [],
        }


def now_iso(offset_hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).isoformat()


def test_store_transaction_and_prediction_persistence(tmp_path, monkeypatch):
    store = LiveStore(tmp_path / "live.sqlite3")
    # Avoid sending emails
    monkeypatch.setattr(lp, 'send_alert_email', lambda *a, **k: [])

    model = FakeModel(prob=0.2, risk='LOW')

    txn = {
        'transaction_id': 'T1',
        'timestamp': now_iso(),
        'amount': 10.0,
        'currency': 'INR',
        'payment_method': 'card',
        'status': 'captured',
        'source': 'TEST',
    }

    res = lp.process_transaction(txn, store=store, model=model)
    assert res['status'] == 'processed'
    stored = store.get_transaction('T1')
    assert stored is not None
    # fraud_probability comes from joined fraud_predictions
    assert 'fraud_probability' in stored
    assert pytest.approx(stored['fraud_probability'], rel=1e-3) == 0.2


def test_duplicate_transaction_handling(tmp_path, monkeypatch):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr(lp, 'send_alert_email', lambda *a, **k: [])
    model = FakeModel(prob=0.1, risk='LOW')

    txn = {
        'transaction_id': 'DUP1',
        'timestamp': now_iso(),
        'amount': 5.0,
        'currency': 'INR',
        'payment_method': 'upi',
        'status': 'captured',
        'source': 'TEST',
    }

    first = lp.process_transaction(txn, store=store, model=model)
    assert first['status'] == 'processed'
    second = lp.process_transaction(txn, store=store, model=model)
    assert second['status'] == 'duplicate'


def test_bucket_aggregation_and_alert_creation(tmp_path, monkeypatch):
    store = LiveStore(tmp_path / "live.sqlite3")
    monkeypatch.setattr(lp, 'send_alert_email', lambda *a, **k: [])

    # Lower thresholds for testing
    store.update_settings({
        'min_transactions': 1,
        'min_history_buckets': 1,
        'zscore_threshold': 3.0,
    })

    # Seed a historical bucket with zero fraud rate
    past_bucket = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    store.upsert_bucket({
        'bucket_start': past_bucket,
        'source': 'TEST',
        'transaction_count': 10,
        'suspicious_count': 0,
        'fraud_rate': 0.0,
        'baseline_rate': 0.0,
        'stddev': None,
        'z_score': 0.0,
    })

    model = FakeModel(prob=0.95, risk='CRITICAL')

    # Create three suspicious transactions in the same current bucket
    results = []
    for i in range(3):
        txn = {
            'transaction_id': f'SPK{i+1}',
            'timestamp': now_iso(),
            'amount': 100.0 + i,
            'currency': 'INR',
            'payment_method': 'card',
            'status': 'captured',
            'source': 'TEST',
        }
        res = lp.process_transaction(txn, store=store, model=model)
        results.append(res)

    # The last transaction should have created an alert
    assert results[-1]['status'] == 'processed'
    assert results[-1]['alert'] is not None
    alerts = store.list_alerts()
    assert len(alerts) >= 1
