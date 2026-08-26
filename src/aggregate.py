"""Aggregate scored transactions into hourly fraud time-series segments."""

from pathlib import Path
import argparse
import json
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "paysim_scored.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "aggregated_timeseries.csv"
DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth_spikes.json"


def aggregate_timeseries(
    input_path: Path,
    output_path: Path,
    ground_truth_path: Path,
) -> pd.DataFrame:
    """Bucket scored transactions into 1-hour slices and compute aggregates."""
    if not input_path.exists():
        raise FileNotFoundError(f"Scored dataset not found: {input_path}")

    print(f"Loading scored transactions from {input_path}...")
    df = pd.read_csv(input_path)
    required = {"timestamp", "region", "device", "type", "isFraud", "fraud_prob"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(missing)}")

    print("Formatting timestamps and bucketing into 1-hour windows...")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["time_bucket"] = df["timestamp"].dt.floor("1h")

    print(f"Aggregating {len(df):,} transactions by (time_bucket, region, device, type)...")
    aggregated = (
        df.groupby(["time_bucket", "region", "device", "type"], as_index=False)
        .agg(
            transaction_count=("isFraud", "size"),
            fraud_count=("isFraud", "sum"),
            mean_fraud_prob=("fraud_prob", "mean"),
        )
    )
    aggregated["fraud_rate"] = aggregated["fraud_count"] / aggregated["transaction_count"]
    aggregated = aggregated.sort_values(
        ["region", "device", "type", "time_bucket"], kind="stable"
    ).reset_index(drop=True)

    print(f"Aggregation complete. Total time-series buckets: {len(aggregated):,}")
    print(f"Date range: {aggregated['time_bucket'].min()} to {aggregated['time_bucket'].max()}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    aggregated.to_csv(output_path, index=False)
    print(f"Saved aggregated timeseries to {output_path} ({output_path.stat().st_size / (1024*1024):.1f} MB).")

    # Sanity check against ground truth spikes
    if ground_truth_path.exists():
        print("\n" + "=" * 80)
        print("SANITY CHECK: Aggregated Rows for Injected Ground-Truth Spike Windows")
        print("=" * 80)
        with open(ground_truth_path) as f:
            spikes = json.load(f)

        for spike in spikes:
            start = pd.to_datetime(spike["start"])
            end = pd.to_datetime(spike["end"])
            region = spike["region"]
            device = spike["device"]
            typ = spike["type"]

            mask = (
                (aggregated["time_bucket"] >= start)
                & (aggregated["time_bucket"] <= end)
                & (aggregated["region"] == region)
                & (aggregated["device"] == device)
                & (aggregated["type"] == typ)
            )
            matches = aggregated[mask]
            print(f"\n>>> [{spike['spike_id']}] Segment: {region} | {device} | {typ} (Window: {start} to {end})")
            print(f"    Target Fraud Rate: {spike['target_fraud_rate']*100:.1f}% (Baseline before spike: {spike['before_fraud_rate']*100:.2f}%)")
            if not matches.empty:
                print(matches[[
                    "time_bucket", "region", "device", "type",
                    "transaction_count", "fraud_count", "fraud_rate", "mean_fraud_prob"
                ]].to_string(index=False))
            else:
                print("    [WARNING] No matching buckets found!")
        print("=" * 80 + "\n")
    else:
        print(f"Ground truth file not found: {ground_truth_path}")

    return aggregated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    aggregate_timeseries(args.input, args.output, args.ground_truth)