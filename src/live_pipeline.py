"""Shared transaction processing pipeline for SentinelPay.

Used identically by Razorpay webhooks, the controlled test simulator, and batch ingestion.
Performs:
1. Transaction validation & normalization
2. Idempotency checks
3. ML Fraud risk scoring
4. Time-bucket aggregation
5. Rolling historical baseline & Z-Score spike detection
6. Alert generation / deduplication / severity escalation
7. Email notification dispatch & audit logging
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Optional
import uuid

import joblib
import numpy as np
import pandas as pd

from src.live_store import LiveStore
from src.notifications import send_alert_email

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_MODEL_PATH = PROJECT_ROOT / "data" / "live_fraud_model.joblib"


class LiveModelUnavailable(RuntimeError):
    pass


def _utc_timestamp(value: str | datetime) -> datetime:
    timestamp = pd.to_datetime(value, utc=True).to_pydatetime()
    return timestamp.replace(tzinfo=None)


def normalize_razorpay_payment(event: dict) -> dict:
    """Map documented Razorpay payment webhook fields to SentinelPay internal schema."""
    payment = event.get("payload", {}).get("payment", {}).get("entity")
    if not isinstance(payment, dict) or not payment.get("id"):
        raise ValueError("Webhook payload does not contain a Razorpay payment entity")
    created_at = payment.get("created_at")
    if not isinstance(created_at, (int, float)):
        raise ValueError("Razorpay payment is missing created_at")
    return {
        "transaction_id": str(payment["id"]),
        "timestamp": datetime.fromtimestamp(created_at, tz=timezone.utc).replace(tzinfo=None).isoformat(),
        "amount": float(payment.get("amount", 0)) / 100.0,
        "currency": str(payment.get("currency") or "INR"),
        "payment_method": str(payment.get("method") or "unknown"),
        "status": str(payment.get("status") or "unknown"),
        "order_id": payment.get("order_id"),
        "customer_id": payment.get("contact") or payment.get("email"),
        "source": "RAZORPAY_TEST",
        "raw_event_id": str(event.get("id") or ""),
    }


class LiveFraudModel:
    """Inference wrapper for the live-compatible XGBoost model."""

    def __init__(self, model_path: Path = LIVE_MODEL_PATH) -> None:
        self.model_path = model_path
        self._model = None

    def _load(self):
        if self._model is None:
            if not self.model_path.exists():
                raise LiveModelUnavailable(
                    f"Live model not found at {self.model_path}. Run: python3 src/train_live_model.py"
                )
            self._model = joblib.load(self.model_path)
        return self._model

    @staticmethod
    def features(transaction: dict) -> pd.DataFrame:
        timestamp = _utc_timestamp(transaction["timestamp"])
        method = str(transaction.get("payment_method", "")).lower()
        return pd.DataFrame([{
            "amount": float(transaction["amount"]),
            "hour_of_day": int(timestamp.hour),
            "method_card": float(method == "card"),
            "method_upi": float(method == "upi"),
            "method_netbanking": float(method == "netbanking"),
            "method_wallet": float(method == "wallet"),
            "method_other": float(method not in {"card", "upi", "netbanking", "wallet"}),
        }])

    def predict(self, transaction: dict, threshold: float = 0.50) -> dict:
        model = self._load()
        features = self.features(transaction)
        probability = float(model.predict_proba(features)[0, 1])
        probability = min(1.0, max(0.0, probability)) if math.isfinite(probability) else 0.0

        if probability >= 0.85:
            risk_level = "CRITICAL"
        elif probability >= threshold:
            risk_level = "HIGH"
        elif probability >= threshold * 0.6:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        contribution = []
        try:
            import xgboost as xgb
            booster = model.get_booster()
            contribs = booster.predict(xgb.DMatrix(features), pred_contribs=True)[0][:-1]
            feature_labels = {
                "amount": "Transaction Amount",
                "hour_of_day": "Hour of Day",
                "method_card": "Card Payment Method",
                "method_upi": "UPI Payment Method",
                "method_netbanking": "Netbanking Method",
                "method_wallet": "Wallet Method",
                "method_other": "Unusual Payment Channel",
            }
            for name, val in sorted(zip(features.columns, contribs), key=lambda x: abs(x[1]), reverse=True)[:3]:
                if abs(val) > 0.001:
                    contribution.append({
                        "feature": feature_labels.get(name, name),
                        "contribution": round(float(val), 4),
                        "direction": "elevates risk" if val > 0 else "reduces risk",
                    })
        except Exception:
            contribution = []

        return {
            "fraud_probability": probability,
            "risk_level": risk_level,
            "model_status": "scored",
            "explanation": contribution,
        }


def _bucket_start(timestamp: str) -> str:
    return _utc_timestamp(timestamp).replace(minute=0, second=0, microsecond=0).isoformat()


def _finite(value: float | None, default: float = 0.0) -> float:
    return float(value) if value is not None and math.isfinite(float(value)) else default


def _json_safe(value):
    """Convert numpy scalars so slice attribution JSON and SQLite binds stay native Python."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return float(value) if isinstance(value, np.floating) else int(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _resolve_alert_multiplier(
    rate: float,
    baseline: float | None,
    slice_attr: dict | None,
    z_score: float,
) -> float:
    """Always return a finite top-level spike multiplier for spike_alerts.multiplier."""
    if baseline is not None:
        try:
            base = float(baseline)
            if base > 0:
                overall = float(rate) / base
                if math.isfinite(overall) and overall > 0:
                    return round(overall, 1)
        except (TypeError, ValueError):
            pass

    top = (slice_attr or {}).get("top_slice") or {}
    top_mult = top.get("multiplier")
    if top_mult is not None:
        try:
            slice_mult = float(top_mult)
            if math.isfinite(slice_mult) and slice_mult > 0:
                return round(slice_mult, 1)
        except (TypeError, ValueError):
            pass

    try:
        proxy = float(z_score) if z_score else 1.0
    except (TypeError, ValueError):
        proxy = 1.0
    if math.isfinite(proxy) and proxy > 0:
        return round(proxy, 1)
    return 1.0


def process_transaction(
    transaction: dict,
    store: Optional[LiveStore] = None,
    model: Optional[LiveFraudModel] = None,
) -> dict:
    """Shared transaction processing pipeline for SentinelPay."""
    required = {"transaction_id", "timestamp", "amount", "currency", "payment_method", "status", "source"}
    missing = required - transaction.keys()
    if missing:
        raise ValueError(f"Transaction is missing required fields: {', '.join(sorted(missing))}")
    if float(transaction["amount"]) < 0:
        raise ValueError("Transaction amount cannot be negative")

    transaction = {
        **transaction,
        "timestamp": _utc_timestamp(transaction["timestamp"]).isoformat(),
        "raw_event_id": transaction.get("raw_event_id"),
    }

    store = store or LiveStore()
    model = model or LiveFraudModel()

    # Dynamic settings
    risk_threshold = float(store.get_setting("fraud_classification_threshold", "0.50"))
    min_tx = int(store.get_setting("min_transactions", "20"))
    min_history = int(store.get_setting("min_history_buckets", "12"))
    zscore_thresh = float(store.get_setting("zscore_threshold", "3.0"))
    avg_loss_rate = float(store.get_setting("average_loss_rate", "0.60"))

    # 1. Idempotent store
    if not store.store_transaction(transaction):
        return {"status": "duplicate", "transaction_id": transaction["transaction_id"]}

    # 2. Fraud scoring
    try:
        prediction = model.predict(transaction, threshold=risk_threshold)
    except LiveModelUnavailable:
        prediction = {"fraud_probability": None, "risk_level": "MANUAL_REVIEW", "model_status": "unavailable", "explanation": []}
    except Exception:
        prediction = {"fraud_probability": None, "risk_level": "MANUAL_REVIEW", "model_status": "failed", "explanation": []}

    store.store_prediction(transaction["transaction_id"], prediction)

    # 3. Bucket aggregation
    bucket_start = _bucket_start(transaction["timestamp"])
    total, suspicious = store.bucket_counts(bucket_start, transaction["source"])
    rate = suspicious / total if total > 0 else 0.0

    # 4. Historical baseline calculation
    history = store.recent_bucket_rows(transaction["source"], bucket_start)
    history_rates = [_finite(row["fraud_rate"]) for row in history if int(row["transaction_count"]) >= min_tx]

    baseline = float(np.mean(history_rates)) if len(history_rates) >= min_history else None
    stddev = float(np.std(history_rates, ddof=1)) if len(history_rates) >= min_history else None

    # 5. Safe Z-Score computation
    if baseline is None:
        z_score = 0.0
    elif stddev is not None and stddev > 1e-9:
        z_score = (rate - baseline) / stddev
    elif rate > baseline and suspicious >= 3:
        # Zero-variance jump with suspicious volume
        z_score = zscore_thresh + 2.0
    else:
        z_score = 0.0

    bucket = {
        "bucket_start": bucket_start,
        "source": transaction["source"],
        "transaction_count": total,
        "suspicious_count": suspicious,
        "fraud_rate": _finite(rate),
        "baseline_rate": baseline,
        "stddev": stddev,
        "z_score": _finite(z_score),
    }
    store.upsert_bucket(bucket)

    # 6. Spike Detection & Alert Deduplication
    alert = None
    is_spike = (total >= min_tx) and (suspicious >= 3) and (z_score >= zscore_thresh)

    if is_spike:
        exposure = round(float(transaction["amount"]) * suspicious * avg_loss_rate, 2)
        slice_attr = _json_safe(store.compute_slice_attribution(bucket_start, transaction["source"]))
        multiplier = _resolve_alert_multiplier(rate, baseline, slice_attr, z_score)
        severity = "CRITICAL" if z_score >= 6.0 or multiplier >= 5.0 else "HIGH"

        existing_alert = store.alert_exists(bucket_start, transaction["source"])
        if existing_alert:
            # Deduplicate & escalate if severity increases
            old_sev = existing_alert["severity"]
            escalation = (old_sev == "HIGH" and severity == "CRITICAL")
            effective_sev = "CRITICAL" if (old_sev == "CRITICAL" or severity == "CRITICAL") else severity

            # Update timeline
            current_timeline = []
            try:
                current_timeline = json.loads(existing_alert.get("timeline_json") or "[]")
            except Exception:
                current_timeline = []

            if escalation or suspicious > existing_alert.get("affected_transactions", 0) + 10:
                current_timeline.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "ESCALATED" if escalation else "BURST_EXPANDED",
                    "severity": effective_sev,
                    "rate": round(rate, 4),
                    "exposure": max(existing_alert.get("potential_exposure", 0), exposure),
                    "z_score": round(max(existing_alert.get("anomaly_score", 0), z_score), 1),
                })

            updated_alert = {
                "alert_id": existing_alert["alert_id"],
                "window_end": bucket_start,
                "current_rate": rate,
                "multiplier": multiplier,
                "anomaly_score": max(existing_alert["anomaly_score"], z_score),
                "severity": effective_sev,
                "affected_transactions": max(existing_alert["affected_transactions"], suspicious),
                "potential_exposure": max(existing_alert["potential_exposure"], exposure),
                "root_cause_json": json.dumps(prediction["explanation"] or json.loads(existing_alert["root_cause_json"] or "[]")),
                "slice_attribution_json": json.dumps(slice_attr or json.loads(existing_alert.get("slice_attribution_json") or "{}")),
                "timeline_json": json.dumps(current_timeline),
            }
            store.update_alert(updated_alert, escalation=escalation)
            alert = {**existing_alert, **updated_alert, "slice_attribution": slice_attr, "timeline": current_timeline}
        else:
            # Create new alert
            now_iso = datetime.now(timezone.utc).isoformat()
            initial_timeline = [{
                "timestamp": now_iso,
                "event": "DETECTED",
                "severity": severity,
                "rate": round(rate, 4),
                "exposure": exposure,
                "z_score": round(z_score, 1),
            }]
            alert = {
                "alert_id": f"ALERT-{uuid.uuid4().hex[:8].upper()}",
                "detected_at": now_iso,
                "window_start": bucket_start,
                "window_end": bucket_start,
                "source": transaction["source"],
                "baseline_rate": _finite(baseline),
                "current_rate": rate,
                "multiplier": multiplier,
                "anomaly_score": z_score,
                "severity": severity,
                "status": "INVESTIGATING",
                "affected_transactions": suspicious,
                "potential_exposure": exposure,
                "root_cause_json": json.dumps(prediction["explanation"]),
                "slice_attribution_json": json.dumps(slice_attr),
                "timeline_json": json.dumps(initial_timeline),
            }
            store.create_alert(alert)
            alert["slice_attribution"] = slice_attr
            alert["timeline"] = initial_timeline

            # Trigger email notifications
            recipients = store.list_recipients(enabled_only=True)
            if recipients:
                notification_results = send_alert_email(alert, recipients)
                for res in notification_results:
                    store.record_notification(alert["alert_id"], res)

    return {
        "status": "processed",
        "transaction_id": transaction["transaction_id"],
        "prediction": prediction,
        "bucket": bucket,
        "alert": alert,
    }
