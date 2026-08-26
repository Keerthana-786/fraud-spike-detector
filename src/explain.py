"""Root-cause explainability module using dimensional ranking and SHAP tree explanations."""

from pathlib import Path
import argparse
import json
import joblib
import numpy as np
import pandas as pd
import shap

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DETECTED_PATH = PROJECT_ROOT / "data" / "detected_spikes.csv"
DEFAULT_AGGREGATED_PATH = PROJECT_ROOT / "data" / "aggregated_timeseries.csv"
DEFAULT_SCORED_PATH = PROJECT_ROOT / "data" / "paysim_scored.csv"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "xgb_fraud_model.joblib"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "spike_explanations.json"

SEGMENT_COLUMNS = ["region", "device", "type"]


def build_features_for_shap(df_slice: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct exact feature columns used by the XGBoost model."""
    timestamps = pd.to_datetime(df_slice["timestamp"])
    features = pd.DataFrame(index=df_slice.index)
    features["amount"] = df_slice["amount"].astype(np.float32)
    features["oldbalanceOrg"] = df_slice["oldbalanceOrg"].astype(np.float32)
    features["newbalanceOrig"] = df_slice["newbalanceOrig"].astype(np.float32)
    features["oldbalanceDest"] = df_slice["oldbalanceDest"].astype(np.float32)
    features["newbalanceDest"] = df_slice["newbalanceDest"].astype(np.float32)
    features["orig_balance_delta"] = (
        df_slice["newbalanceOrig"] - df_slice["oldbalanceOrg"]
    ).astype(np.float32)
    features["dest_balance_delta"] = (
        df_slice["newbalanceDest"] - df_slice["oldbalanceDest"]
    ).astype(np.float32)
    features["hour_of_day"] = timestamps.dt.hour.astype(np.int8)

    for t in ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]:
        features[f"type_{t}"] = (df_slice["type"] == t).astype(np.float32)

    return features


def cluster_into_events(detected_df: pd.DataFrame) -> list[dict]:
    """Group consecutive hourly spikes for the same segment into continuous spike events."""
    events = []
    if detected_df.empty:
        return events

    detected_df = detected_df.sort_values(SEGMENT_COLUMNS + ["time_bucket"]).copy()
    detected_df["time_bucket"] = pd.to_datetime(detected_df["time_bucket"])

    for (region, device, typ), group in detected_df.groupby(SEGMENT_COLUMNS):
        group = group.sort_values("time_bucket")
        group["time_diff"] = group["time_bucket"].diff()

        # Identify new event if gap > 3 hours
        new_event = group["time_diff"] > pd.Timedelta(hours=3)
        group["event_id"] = new_event.cumsum()

        for event_idx, event_rows in group.groupby("event_id"):
            start_time = event_rows["time_bucket"].min()
            end_time = event_rows["time_bucket"].max()
            max_z = float(event_rows["z_score"].max())
            mean_rate = float(event_rows["fraud_rate"].mean())
            mean_base = float(event_rows["rolling_mean"].mean()) if event_rows["rolling_mean"].notna().any() else 0.0
            total_txns = int(event_rows["transaction_count"].sum())
            total_frauds = int(event_rows["fraud_count"].sum())

            events.append({
                "region": region,
                "device": device,
                "type": typ,
                "start": str(start_time),
                "end": str(end_time),
                "duration_hours": len(event_rows),
                "max_z_score": max_z,
                "avg_fraud_rate": mean_rate,
                "avg_baseline_rate": mean_base,
                "total_transactions": total_txns,
                "total_frauds": total_frauds,
                "buckets": event_rows.to_dict(orient="records"),
            })

    # Sort events by maximum z-score and volume descending
    events.sort(key=lambda e: (e["max_z_score"], e["total_frauds"]), reverse=True)
    return events


def explain_spikes(
    detected_path: Path = DEFAULT_DETECTED_PATH,
    aggregated_path: Path = DEFAULT_AGGREGATED_PATH,
    scored_path: Path = DEFAULT_SCORED_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    top_n_events: int = 15,
) -> list[dict]:
    """Generate SHAP feature attributions and human-readable explanations for detected spikes."""
    if not detected_path.exists():
        raise FileNotFoundError(f"Detected spikes file not found: {detected_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    if not scored_path.exists():
        raise FileNotFoundError(f"Scored dataset not found: {scored_path}")

    print(f"Loading detected spikes from {detected_path}...")
    detected_df = pd.read_csv(detected_path)
    events = cluster_into_events(detected_df)
    print(f"Clustered detected spikes into {len(events)} distinct spike events.")

    print(f"Loading XGBoost model from {model_path} for TreeSHAP analysis...")
    model = joblib.load(model_path)
    explainer = shap.TreeExplainer(model)

    print(f"Loading scored transactions from {scored_path} (reading relevant columns)...")
    scored_df = pd.read_csv(
        scored_path,
        usecols=[
            "timestamp", "region", "device", "type", "amount",
            "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest",
            "newbalanceDest", "isFraud", "fraud_prob"
        ]
    )
    scored_df["timestamp"] = pd.to_datetime(scored_df["timestamp"])

    explanations = []
    print("\n--- Computing SHAP Root-Cause Explanations for Spike Events ---")

    # Analyze top events
    target_events = events[:top_n_events]

    for idx, ev in enumerate(target_events, 1):
        start_ts = pd.Timestamp(ev["start"])
        end_ts = pd.Timestamp(ev["end"]) + pd.Timedelta(hours=1)
        region = ev["region"]
        device = ev["device"]
        typ = ev["type"]

        # Filter slice transactions in this window
        mask = (
            (scored_df["timestamp"] >= start_ts)
            & (scored_df["timestamp"] <= end_ts)
            & (scored_df["region"] == region)
            & (scored_df["device"] == device)
            & (scored_df["type"] == typ)
        )
        slice_txns = scored_df[mask]

        if slice_txns.empty:
            continue

        # Select top high-risk / fraudulent transactions for SHAP explanation
        sample_frauds = slice_txns.sort_values("fraud_prob", ascending=False).head(50)
        X_sample = build_features_for_shap(sample_frauds)

        # Compute SHAP values
        shap_vals = explainer.shap_values(X_sample)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1]

        mean_abs_shap = np.abs(shap_vals).mean(axis=0)
        feature_importance = pd.DataFrame({
            "feature": X_sample.columns,
            "mean_shap": mean_abs_shap,
        }).sort_values("mean_shap", ascending=False)

        top_features = feature_importance.head(4)["feature"].tolist()
        top_shap_dict = {
            row["feature"]: round(float(row["mean_shap"]), 4)
            for _, row in feature_importance.head(5).iterrows()
        }

        # Calculate multiplier
        base_rate = ev["avg_baseline_rate"]
        spike_rate = ev["avg_fraud_rate"]
        if base_rate > 0:
            multiplier_str = f"{spike_rate / base_rate:.1f}x normal"
        else:
            multiplier_str = "anomalous surge from 0% baseline"

        z_str = f"{ev['max_z_score']:.1f}" if ev['max_z_score'] < 900 else "inf"

        # Generate Human-Readable Plain-English Narrative
        date_str = f"{start_ts.strftime('%Y-%m-%d %H:%M')} to {end_ts.strftime('%H:%M')}"
        top_feature_desc = ", ".join(top_features[:3])

        narrative = (
            f"Spike detected {date_str}, driven by {typ}/{device} transactions in {region} region. "
            f"Observed fraud rate of {spike_rate*100:.1f}% ({multiplier_str}, z={z_str}). "
            f"SHAP transaction root-cause attributions highlight {top_feature_desc} as primary risk drivers."
        )

        explanation_record = {
            "event_id": f"ALERT-EVENT-{idx:03d}",
            "region": region,
            "device": device,
            "type": typ,
            "start_time": ev["start"],
            "end_time": ev["end"],
            "duration_hours": ev["duration_hours"],
            "max_z_score": round(ev["max_z_score"], 2),
            "avg_fraud_rate": round(ev["avg_fraud_rate"], 4),
            "avg_baseline_rate": round(ev["avg_baseline_rate"], 5),
            "total_transactions": ev["total_transactions"],
            "total_frauds": ev["total_frauds"],
            "multiplier_summary": multiplier_str,
            "top_shap_features": top_shap_dict,
            "summary_narrative": narrative,
        }
        explanations.append(explanation_record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(explanations, f, indent=2)
    print(f"\nSaved {len(explanations)} spike explanations to {output_path}")

    # Print Top Plain-English Explanations
    print("\n" + "=" * 80)
    print("PLAIN-ENGLISH ROOT-CAUSE SPIKE EXPLANATIONS")
    print("=" * 80)
    for expl in explanations[:6]:
        print(f"\n[{expl['event_id']}] {expl['region']} | {expl['device']} | {expl['type']}")
        print(f"  Narrative: {expl['summary_narrative']}")
        print(f"  Top SHAP Features: {expl['top_shap_features']}")
    print("=" * 80 + "\n")

    return explanations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detected", type=Path, default=DEFAULT_DETECTED_PATH)
    parser.add_argument("--aggregated", type=Path, default=DEFAULT_AGGREGATED_PATH)
    parser.add_argument("--scored", type=Path, default=DEFAULT_SCORED_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-n", type=int, default=15)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    explain_spikes(
        detected_path=args.detected,
        aggregated_path=args.aggregated,
        scored_path=args.scored,
        model_path=args.model,
        output_path=args.output,
        top_n_events=args.top_n,
    )
    