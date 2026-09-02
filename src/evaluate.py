"""Evaluate spike detection performance and compute operational cost metrics."""

from pathlib import Path
import argparse
import json
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DETECTED_PATH = PROJECT_ROOT / "data" / "detected_spikes.csv"
DEFAULT_AGGREGATED_PATH = PROJECT_ROOT / "data" / "aggregated_timeseries.csv"
DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth_spikes.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "evaluation_report.json"

# Configurable operational financial costs
COST_PER_FALSE_ALERT = 50.0        # $50 analyst manual review cost per non-injected alert
COST_PER_MISSED_SPIKE = 5000.0     # $5,000 unchecked fraud ring damage per missed spike

SEGMENT_COLUMNS = ["region", "device", "type"]


def _classifier_metrics(scored_path: Path, train_ratio: float = 0.6, validation_ratio: float = 0.2) -> dict:
    """Measure classifier metrics on chronological validation and held-out slices."""
    if not scored_path.exists():
        return {"status": "UNAVAILABLE", "reason": "Scored classifier artifact not found."}
    required = {"timestamp", "isFraud", "fraud_prob"}
    frame = pd.read_csv(scored_path, usecols=lambda column: column in required)
    if not required.issubset(frame.columns):
        return {"status": "UNAVAILABLE", "reason": "Scored artifact lacks isFraud, fraud_prob, or timestamp."}
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    train_end = int(len(frame) * train_ratio)
    validation_end = int(len(frame) * (train_ratio + validation_ratio))
    validation = frame.iloc[train_end:validation_end]
    held_out = frame.iloc[validation_end:]
    if validation.empty or held_out.empty or validation["isFraud"].nunique() < 2 or held_out["isFraud"].nunique() < 2:
        return {"status": "UNAVAILABLE", "reason": "Held-out slice is empty or has one class."}
    validation_predictions = (validation["fraud_prob"] >= 0.5).astype(int)
    predictions = (held_out["fraud_prob"] >= 0.5).astype(int)
    negatives = int((held_out["isFraud"] == 0).sum())
    false_positives = int(((predictions == 1) & (held_out["isFraud"] == 0)).sum())
    validation_negatives = int((validation["isFraud"] == 0).sum())
    validation_false_positives = int(((validation_predictions == 1) & (validation["isFraud"] == 0)).sum())
    return {
        "status": "MEASURED",
        "method": "Chronological 60/20/20 split; threshold 0.50",
        "train_size": train_end,
        "validation": {
            "validation_size": len(validation),
            "fraud_count": int(validation["isFraud"].sum()),
            "precision": float(precision_score(validation["isFraud"], validation_predictions, zero_division=0)),
            "recall": float(recall_score(validation["isFraud"], validation_predictions, zero_division=0)),
            "f1": float(f1_score(validation["isFraud"], validation_predictions, zero_division=0)),
            "false_positive_rate": validation_false_positives / validation_negatives if validation_negatives else 0.0,
        },
        "held_out_test_size": len(held_out),
        "fraud_count": int(held_out["isFraud"].sum()),
        "precision": float(precision_score(held_out["isFraud"], predictions, zero_division=0)),
        "recall": float(recall_score(held_out["isFraud"], predictions, zero_division=0)),
        "f1": float(f1_score(held_out["isFraud"], predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(held_out["isFraud"], held_out["fraud_prob"])),
        "false_positive_rate": false_positives / negatives if negatives else 0.0,
        "confusion_matrix": {
            "true_positives": int(((predictions == 1) & (held_out["isFraud"] == 1)).sum()),
            "false_positives": false_positives,
            "true_negatives": int(((predictions == 0) & (held_out["isFraud"] == 0)).sum()),
            "false_negatives": int(((predictions == 0) & (held_out["isFraud"] == 1)).sum()),
        },
    }


def cluster_alerts(flagged_df: pd.DataFrame) -> list[dict]:
    """Group consecutive hourly flagged buckets into alert events."""
    alert_events = []
    if flagged_df.empty:
        return alert_events

    df = flagged_df.sort_values(SEGMENT_COLUMNS + ["time_bucket"]).copy()
    df["time_bucket"] = pd.to_datetime(df["time_bucket"])

    for (region, device, typ), group in df.groupby(SEGMENT_COLUMNS):
        group = group.sort_values("time_bucket")
        group["gap"] = group["time_bucket"].diff() > pd.Timedelta(hours=3)
        group["event_id"] = group["gap"].cumsum()

        for _, ev_rows in group.groupby("event_id"):
            alert_events.append({
                "region": region,
                "device": device,
                "type": typ,
                "start": ev_rows["time_bucket"].min(),
                "end": ev_rows["time_bucket"].max(),
                "buckets_count": len(ev_rows),
                "max_z_score": float(ev_rows["z_score"].max()),
                "avg_fraud_rate": float(ev_rows["fraud_rate"].mean()),
                "total_transactions": int(ev_rows["transaction_count"].sum()),
                "total_frauds": int(ev_rows["fraud_count"].sum()),
            })
    return alert_events


def evaluate_detector(
    detected_path: Path = DEFAULT_DETECTED_PATH,
    aggregated_path: Path = DEFAULT_AGGREGATED_PATH,
    ground_truth_path: Path = DEFAULT_GROUND_TRUTH_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    cost_per_false_alert: float = COST_PER_FALSE_ALERT,
    cost_per_missed_spike: float = COST_PER_MISSED_SPIKE,
    scored_path: Path = PROJECT_ROOT / "data" / "paysim_scored.csv",
) -> dict:
    """Compute precision, recall, F1, FPR, and operational cost metrics."""
    if not detected_path.exists():
        raise FileNotFoundError(f"Detected spikes not found: {detected_path}")
    if not ground_truth_path.exists():
        raise FileNotFoundError(f"Ground truth not found: {ground_truth_path}")
    if not aggregated_path.exists():
        raise FileNotFoundError(f"Aggregated timeseries not found: {aggregated_path}")

    detected_df = pd.read_csv(detected_path)
    detected_df["time_bucket"] = pd.to_datetime(detected_df["time_bucket"])

    aggregated_df = pd.read_csv(aggregated_path)
    total_buckets = len(aggregated_df)

    with open(ground_truth_path) as f:
        ground_truth = json.load(f)
    if isinstance(ground_truth, dict):
        ground_truth = ground_truth.get("spikes", [])

    total_gt_spikes = len(ground_truth)

    # Cluster detected hourly buckets into continuous alert events
    alert_events = cluster_alerts(detected_df)
    total_alert_events = len(alert_events)

    # Match ground truth spikes against alert events
    tp_spikes = 0
    fn_spikes = 0
    spike_details = []

    matched_alert_indices = set()

    for spike in ground_truth:
        s_start = pd.to_datetime(spike["start"])
        s_end = pd.to_datetime(spike["end"])
        s_reg = spike["region"]
        s_dev = spike["device"]
        s_typ = spike["type"]

        caught = False
        matching_alerts = []

        for idx, alert in enumerate(alert_events):
            if (
                alert["region"] == s_reg
                and alert["device"] == s_dev
                and alert["type"] == s_typ
                and not (alert["end"] < s_start or alert["start"] > s_end)
            ):
                caught = True
                matched_alert_indices.add(idx)
                matching_alerts.append(alert)

        if caught:
            tp_spikes += 1
            spike_details.append({
                "spike_id": spike["spike_id"],
                "status": "CAUGHT",
                "region": s_reg,
                "device": s_dev,
                "type": s_typ,
                "window": f"{spike['start']} to {spike['end']}",
                "target_rate": spike.get("target_fraud_rate", 0),
            })
        else:
            fn_spikes += 1
            spike_details.append({
                "spike_id": spike["spike_id"],
                "status": "MISSED",
                "region": s_reg,
                "device": s_dev,
                "type": s_typ,
                "window": f"{spike['start']} to {spike['end']}",
                "target_rate": spike.get("target_fraud_rate", 0),
            })

    # Spike-level metrics. This is an event-level result over a four-event synthetic set.
    spike_recall = tp_spikes / total_gt_spikes if total_gt_spikes else 0.0
    
    # Event-level alert metrics
    tp_alerts = len(matched_alert_indices)
    fp_alerts = total_alert_events - tp_alerts
    alert_recall = tp_alerts / total_gt_spikes if total_gt_spikes else 0.0
    alert_precision = tp_alerts / total_alert_events if total_alert_events else 0.0
    alert_f1 = (
        2 * (alert_precision * alert_recall) / (alert_precision + alert_recall)
        if (alert_precision + alert_recall) > 0
        else 0.0
    )

    # Batch artifacts have spike onset and first flagged bucket, but no persisted
    # incident.created_at. Do not substitute bucket or execution time for delay.
    detection_delay = []
    for spike in ground_truth:
        matches = [
            row for _, row in detected_df.iterrows()
            if row["region"] == spike["region"]
            and row["device"] == spike["device"]
            and row["type"] == spike["type"]
            and pd.to_datetime(row["time_bucket"]) >= pd.to_datetime(spike["start"])
            and pd.to_datetime(row["time_bucket"]) <= pd.to_datetime(spike["end"])
        ]
        detection_delay.append({
            "spike_id": spike["spike_id"],
            "spike_start_timestamp": spike["start"],
            "spike_end_timestamp": spike["end"],
            "incident_id": None,
            "incident_created_at": None,
            "first_flagged_bucket": str(min((row["time_bucket"] for row in matches), default="")),
            "detection_delay_seconds": None,
            "detection_delay_minutes": None,
            "status": "INCIDENT_TIMESTAMP_UNAVAILABLE" if matches else "MISSED_DETECTION",
        })

    # Bucket-level False Positive Rate
    # True negative buckets are all buckets outside ground truth windows that were not flagged
    gt_bucket_count = sum(
        len(aggregated_df[
            (pd.to_datetime(aggregated_df["time_bucket"]) >= pd.to_datetime(s["start"]))
            & (pd.to_datetime(aggregated_df["time_bucket"]) <= pd.to_datetime(s["end"]))
            & (aggregated_df["region"] == s["region"])
            & (aggregated_df["device"] == s["device"])
            & (aggregated_df["type"] == s["type"])
        ])
        for s in ground_truth
    )
    total_negative_buckets = max(1, total_buckets - gt_bucket_count)
    flagged_negative_buckets = len(detected_df) - len(detected_df[
        detected_df.apply(
            lambda row: any(
                row["region"] == s["region"]
                and row["device"] == s["device"]
                and row["type"] == s["type"]
                and pd.to_datetime(s["start"]) <= row["time_bucket"] <= pd.to_datetime(s["end"])
                for s in ground_truth
            ),
            axis=1,
        )
    ])
    fpr_buckets = flagged_negative_buckets / total_negative_buckets

    # Operational Cost Model
    # Expected cost = (FP alerts * cost_per_false_alert) + (FN spikes * cost_per_missed_spike)
    total_operational_cost = (fp_alerts * cost_per_false_alert) + (fn_spikes * cost_per_missed_spike)
    unmitigated_cost = total_gt_spikes * cost_per_missed_spike
    net_savings = unmitigated_cost - total_operational_cost

    classifier = _classifier_metrics(scored_path)
    report = {
        "report_version": "2.0-honest-evaluation",
        "dataset": {
            "name": "PaySim with synthetic controlled spike injection",
            "ground_truth_type": "Synthetic controlled evaluation",
            "ground_truth_event_count": total_gt_spikes,
            "random_seed": 42,
        },
        "experimental_setup": {
            "detector": "Trailing rolling z-score over hourly segment buckets",
            "threshold": 3.0,
            "minimum_transactions": 20,
            "incident_created_timestamps_available": False,
            "execution_latency_is_detection_delay": False,
        },
        "transaction_classifier": classifier,
        "parameters": {
            "cost_per_false_alert_usd": cost_per_false_alert,
            "cost_per_missed_spike_usd": cost_per_missed_spike,
        },
        "spike_level_performance": {
            "total_ground_truth_spikes": total_gt_spikes,
            "true_positive_spikes_caught": tp_spikes,
            "false_negative_spikes_missed": fn_spikes,
            "spike_recall": round(float(spike_recall), 4),
            "event_precision": round(float(alert_precision), 4),
            "event_recall": round(float(alert_recall), 4),
            "event_f1": round(float(alert_f1), 4),
            "true_positives": tp_alerts,
            "false_positives": fp_alerts,
            "false_negatives": fn_spikes,
            "true_negatives": None,
            "sample_size_caveat": "Results are based on only four labeled synthetic spike events and are not statistically robust.",
            "spike_details": spike_details,
        },
        "alert_event_performance": {
            "total_alert_events": total_alert_events,
            "true_positive_alert_events": tp_alerts,
            "false_positive_alert_events": fp_alerts,
            "alert_precision": round(float(alert_precision), 4),
            "alert_f1_score": round(float(alert_f1), 4),
            "bucket_level_false_positive_rate": round(float(fpr_buckets), 6),
        },
        "operational_financial_cost": {
            "classification": "ESTIMATED/ASSUMED, not measured fraud loss",
            "unmitigated_fraud_cost_usd": unmitigated_cost,
            "false_alert_investigation_cost_usd": fp_alerts * cost_per_false_alert,
            "missed_spike_fraud_loss_usd": fn_spikes * cost_per_missed_spike,
            "total_system_operational_cost_usd": total_operational_cost,
            "net_financial_risk_prevented_usd": net_savings,
        },
        "detection_delay": {
            "definition": "incident.created_at - spike_start_timestamp",
            "status": "UNAVAILABLE: batch evaluation artifacts do not contain incident.created_at",
            "events": detection_delay,
            "median_seconds": None,
            "mean_seconds": None,
            "p90_seconds": None,
            "minimum_seconds": None,
            "maximum_seconds": None,
        },
        "limitations": [
            "Only four labeled synthetic spike events are present.",
            "Incident-created timestamps are unavailable, so detection delay is not measurable from this artifact.",
            "No validation split is produced by the current training script.",
            "Financial cost values are assumptions, not confirmed fraud losses.",
            "PaySim and injected labels are not production merchant ground truth.",
        ],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved evaluation report to {report_path}")

    # Print Evaluation Report Scorecard
    print("\n" + "=" * 80)
    print("                FRAUD SPIKE DETECTOR - EVALUATION REPORT")
    print("=" * 80)
    print(f"\n1. SPIKE-LEVEL PERFORMANCE (Ground-Truth Slices):")
    print(f"   • Injected Spikes Caught (TP):   {tp_spikes} / {total_gt_spikes} ({spike_recall*100:.1f}%)")
    print(f"   • Injected Spikes Missed (FN):   {fn_spikes} / {total_gt_spikes}")
    print(f"   • Spike-Level Recall:            {spike_recall:.4f}")

    print(f"\n2. ALERT EVENT & TIME-SERIES METRICS:")
    print(f"   • Total Alert Events Detected:   {total_alert_events}")
    print(f"   • Ground-Truth Matched Alerts:   {tp_alerts}")
    print(f"   • Non-Injected Alert Events:     {fp_alerts} (Natural PaySim bursts)")
    print(f"   • Alert Precision:               {alert_precision:.4f}")
    print(f"   • Alert F1-Score:                {alert_f1:.4f}")
    print(f"   • Bucket-Level False Pos. Rate:  {fpr_buckets*100:.4f}% ({flagged_negative_buckets:,} / {total_negative_buckets:,} buckets)")

    print(f"\n3. OPERATIONAL FINANCIAL COST MODEL:")
    print(f"   • Cost per False Alert:          ${cost_per_false_alert:,.2f}")
    print(f"   • Cost per Missed Spike:         ${cost_per_missed_spike:,.2f}")
    print(f"   • Unmitigated Baseline Cost:     ${unmitigated_cost:,.2f}")
    print(f"   • False Alert Review Cost:       ${fp_alerts * cost_per_false_alert:,.2f}")
    print(f"   • Missed Spike Damage Cost:      ${fn_spikes * cost_per_missed_spike:,.2f}")
    print(f"   --------------------------------------------------------")
    print(f"   • Total System Expected Cost:    ${total_operational_cost:,.2f}")
    print(f"   • Net Financial Risk Prevented:  ${net_savings:,.2f}")
    print("=" * 80 + "\n")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detected", type=Path, default=DEFAULT_DETECTED_PATH)
    parser.add_argument("--aggregated", type=Path, default=DEFAULT_AGGREGATED_PATH)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--cost-false-alert", type=float, default=COST_PER_FALSE_ALERT)
    parser.add_argument("--cost-missed-spike", type=float, default=COST_PER_MISSED_SPIKE)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate_detector(
        detected_path=args.detected,
        aggregated_path=args.aggregated,
        ground_truth_path=args.ground_truth,
        report_path=args.report,
        cost_per_false_alert=args.cost_false_alert,
        cost_per_missed_spike=args.cost_missed_spike,
    )