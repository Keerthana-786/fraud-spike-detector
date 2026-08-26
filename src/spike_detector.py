"""Detect anomalous fraud rate spikes using trailing rolling z-score analysis."""

from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "aggregated_timeseries.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "detected_spikes.csv"
DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth_spikes.json"

# Configurable detection parameters
ZSCORE_THRESHOLD = 3.0       # Threshold for standard deviations above baseline
MIN_TRANSACTIONS = 20        # Minimum volume required to avoid small-sample false alarms
BASELINE_WINDOW = 24         # Trailing rolling window size in hourly buckets
MIN_PERIODS = 12             # Minimum active trailing periods required for stable baseline
MIN_FRAUD_COUNT_TO_FLAG = 3     # Minimum fraud count for any detected spike
MIN_FRAUD_RATE_TO_FLAG = 0.05   # Minimum fraud rate for any detected spike
SEGMENT_COLUMNS = ["region", "device", "type"]


def load_ground_truth(ground_truth_path: Path) -> list[dict]:
    """Load ground-truth spike definitions from JSON."""
    if not ground_truth_path.exists():
        return []
    with open(ground_truth_path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("spikes", [])
    return data if isinstance(data, list) else []


def detect_spikes(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    ground_truth_path: Path = DEFAULT_GROUND_TRUTH_PATH,
    zscore_threshold: float = ZSCORE_THRESHOLD,
    min_transactions: int = MIN_TRANSACTIONS,
    baseline_window: int = BASELINE_WINDOW,
    min_periods: int = MIN_PERIODS,
    min_fraud_count_to_flag: int = MIN_FRAUD_COUNT_TO_FLAG,
    min_fraud_rate_to_flag: float = MIN_FRAUD_RATE_TO_FLAG,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate rolling baseline metrics and detect multi-dimensional fraud spikes."""
    if not input_path.exists():
        raise FileNotFoundError(f"Aggregated timeseries not found: {input_path}")

    print(f"Loading aggregated timeseries from {input_path}...")
    df = pd.read_csv(input_path)
    required = {"time_bucket", *SEGMENT_COLUMNS, "transaction_count", "fraud_count", "fraud_rate"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(missing)}")

    df["time_bucket"] = pd.to_datetime(df["time_bucket"])
    # Ensure strict chronological ordering per segment
    df = df.sort_values(SEGMENT_COLUMNS + ["time_bucket"], kind="stable").reset_index(drop=True)

    print(f"Computing trailing {baseline_window}-bucket rolling baseline (excluding current bucket)...")
    # Mask fraud rate for small volume buckets (< min_transactions) so nighttime noise does not corrupt daytime baseline
    valid_rate = df["fraud_rate"].where(df["transaction_count"] >= min_transactions)
    grouped = valid_rate.groupby([df[c] for c in SEGMENT_COLUMNS], sort=False)

    # Trailing window excluding current bucket using shift(1)
    df["rolling_mean"] = grouped.transform(
        lambda s: s.shift(1).rolling(baseline_window, min_periods=min_periods).mean()
    )
    df["rolling_std"] = grouped.transform(
        lambda s: s.shift(1).rolling(baseline_window, min_periods=min_periods).std()
    )

    # Initialize z-score series
    z_scores = np.zeros(len(df), dtype=float)

    # Case 1: Standard case where rolling_std > 0 and not NaN
    valid_std = (df["rolling_std"] > 1e-9) & df["rolling_std"].notna()
    z_scores[valid_std] = (
        df.loc[valid_std, "fraud_rate"] - df.loc[valid_std, "rolling_mean"]
    ) / df.loc[valid_std, "rolling_std"]

    # Case 2: Zero-variance baseline requires a meaningful count and rate jump.
    zero_variance_jump = (
        (df["rolling_std"].isna() | (df["rolling_std"] <= 1e-9))
        & df["rolling_mean"].notna()
        & (df["rolling_mean"] <= 1e-9)
        & (df["fraud_count"] >= min_fraud_count_to_flag)
        & (df["fraud_rate"] >= min_fraud_rate_to_flag)
    )
    # Assign high z-score so it reliably triggers the alert
    z_scores[zero_variance_jump] = 999.0

    # Case 3: Insufficient history (prior periods < min_periods) -> rolling_mean is NaN -> z_score = 0.0
    insufficient_history = df["rolling_mean"].isna()
    z_scores[insufficient_history] = 0.0

    df["z_score"] = z_scores

    # Flag spikes
    flagged_mask = (
        (df["z_score"] > zscore_threshold)
        & (df["transaction_count"] >= min_transactions)
        & (df["fraud_count"] >= min_fraud_count_to_flag)
        & (df["fraud_rate"] >= min_fraud_rate_to_flag)
    )
    flagged = df[flagged_mask].copy().sort_values("time_bucket", kind="stable").reset_index(drop=True)

    print(f"\nDetection Results (Threshold z > {zscore_threshold}, Min Txns >= {min_transactions}, Min Periods >= {min_periods}, Fraud count >= {min_fraud_count_to_flag}, Fraud rate >= {min_fraud_rate_to_flag:.1%}):")
    print(f"Total time-series buckets analyzed: {len(df):,}")
    print(f"Total anomalous buckets flagged:     {len(flagged):,}")

    output_columns = [
        "time_bucket",
        *SEGMENT_COLUMNS,
        "transaction_count",
        "fraud_count",
        "fraud_rate",
        "rolling_mean",
        "rolling_std",
        "z_score",
    ]
    if "mean_fraud_prob" in df.columns:
        output_columns.append("mean_fraud_prob")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    flagged[output_columns].to_csv(output_path, index=False)
    print(f"Saved detected spikes to {output_path}")

    # Cross-check against ground truth
    ground_truth = load_ground_truth(ground_truth_path)
    if ground_truth:
        print("\n" + "=" * 80)
        print("CROSS-CHECK AGAINST GROUND TRUTH SPIKES")
        print("=" * 80)

        caught_count = 0
        missed_count = 0
        matched_flagged_indices = set()

        for spike in ground_truth:
            start = pd.to_datetime(spike["start"])
            end = pd.to_datetime(spike["end"])
            region = spike["region"]
            device = spike["device"]
            typ = spike["type"]

            # Check if any flagged row overlaps this spike window and slice
            matches = flagged[
                (flagged["time_bucket"] >= start)
                & (flagged["time_bucket"] <= end)
                & (flagged["region"] == region)
                & (flagged["device"] == device)
                & (flagged["type"] == typ)
            ]

            if not matches.empty:
                caught_count += 1
                matched_flagged_indices.update(matches.index.tolist())
                max_z = matches["z_score"].max()
                z_str = f"{max_z:.2f}" if max_z < 900 else "inf (0-baseline jump)"
                print(f"[CAUGHT] {spike['spike_id']}: {region} | {device} | {typ} ({start} to {end})")
                print(f"         Matched {len(matches)} hourly buckets. Max z-score: {z_str}, Average Fraud Rate: {matches['fraud_rate'].mean()*100:.1f}%")
            else:
                missed_count += 1
                print(f"[MISSED] {spike['spike_id']}: {region} | {device} | {typ} ({start} to {end})")

        unmatched_flags = flagged[~flagged.index.isin(matched_flagged_indices)]
        extra_flags_count = len(unmatched_flags)

        print("\nSummary Cross-Check Scorecard:")
        print(f"  • Injected Ground Truth Spikes Caught: {caught_count} / {len(ground_truth)} ({caught_count/len(ground_truth)*100:.1f}%)")
        print(f"  • Injected Ground Truth Spikes Missed: {missed_count} / {len(ground_truth)}")
        print(f"  • Extra / Non-Injected Flagged Buckets: {extra_flags_count}")
        if extra_flags_count > 0:
            print("\nSample extra flagged buckets (natural PaySim anomalies / spikes):")
            print(unmatched_flags.head(5)[output_columns].to_string(index=False))
        print("=" * 80 + "\n")

    return df, flagged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    parser.add_argument("--threshold", type=float, default=ZSCORE_THRESHOLD)
    parser.add_argument("--min-txns", type=int, default=MIN_TRANSACTIONS)
    parser.add_argument("--window", type=int, default=BASELINE_WINDOW)
    parser.add_argument("--min-periods", type=int, default=MIN_PERIODS)
    parser.add_argument("--min-fraud-count", type=int, default=MIN_FRAUD_COUNT_TO_FLAG)
    parser.add_argument("--min-fraud-rate", type=float, default=MIN_FRAUD_RATE_TO_FLAG)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    detect_spikes(
        args.input,
        args.output,
        args.ground_truth,
        zscore_threshold=args.threshold,
        min_transactions=args.min_txns,
        baseline_window=args.window,
        min_periods=args.min_periods,
        min_fraud_count_to_flag=args.min_fraud_count,
        min_fraud_rate_to_flag=args.min_fraud_rate,
    )