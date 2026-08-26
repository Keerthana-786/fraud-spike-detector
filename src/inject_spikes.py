"""Inject synthetic fraud spike events into enriched PaySim dataset."""

from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "paysim_enriched.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "paysim_spiked.csv"
DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth_spikes.json"
SEED = 42
# Define 4 targeted artificial fraud spike scenarios
SPIKE_CONFIGS = [
    {
        "spike_id": "SPIKE-001",
        "start": "2024-01-07 14:00:00",
        "end": "2024-01-07 18:00:00",
        "region": "North",
        "device": "mobile",
        "type": "TRANSFER",
        "target_fraud_rate": 0.25,
        "description": "Coordinated mobile transfer credential stuffing attack in North region",
    },
    {
        "spike_id": "SPIKE-002",
        "start": "2024-01-09 14:00:00",
        "end": "2024-01-09 18:00:00",
        "region": "West",
        "device": "web",
        "type": "CASH_OUT",
        "target_fraud_rate": 0.30,
        "description": "Automated high-velocity web cash-out burst in West region",
    },
    {
        "spike_id": "SPIKE-003",
        "start": "2024-01-11 14:00:00",
        "end": "2024-01-11 18:00:00",
        "region": "South",
        "device": "pos",
        "type": "PAYMENT",
        "target_fraud_rate": 0.20,
        "description": "Compromised retail POS malware burst in South region",
    },
    {
        "spike_id": "SPIKE-004",
        "start": "2024-01-13 14:00:00",
        "end": "2024-01-13 18:00:00",
        "region": "East",
        "device": "atm",
        "type": "CASH_OUT",
        "target_fraud_rate": 0.35,
        "description": "ATM skimming and rapid cash-out ring in East region",
    },
]


def inject_spikes(
    input_path: Path,
    output_path: Path,
    ground_truth_path: Path,
    seed: int = SEED,
) -> tuple[pd.DataFrame, list[dict]]:
    """Inject artificial fraud spikes into specific slices and record ground truth."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input enriched dataset not found: {input_path}")

    print(f"Loading enriched data from {input_path}...")
    df = pd.read_csv(input_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"Loaded {len(df):,} rows.")

    rng = np.random.default_rng(seed)
    ground_truth = []
    summary_records = []

    print("\n--- Injecting Fraud Spikes ---")
    for cfg in SPIKE_CONFIGS:
        start_ts = pd.Timestamp(cfg["start"])
        end_ts = pd.Timestamp(cfg["end"])
        target_region = cfg["region"]
        target_device = cfg["device"]
        target_type = cfg["type"]
        target_rate = cfg["target_fraud_rate"]

        # Match slice
        mask = (
            (df["timestamp"] >= start_ts)
            & (df["timestamp"] <= end_ts)
            & (df["region"] == target_region)
            & (df["device"] == target_device)
            & (df["type"] == target_type)
        )
        slice_indices = df[mask].index
        slice_total = len(slice_indices)
        if slice_total == 0:
            print(f"Warning: No transactions found for spike {cfg['spike_id']}")
            continue

        existing_frauds = int(df.loc[slice_indices, "isFraud"].sum())
        before_rate = existing_frauds / slice_total

        # Target fraud count
        target_fraud_count = int(np.ceil(slice_total * target_rate))
        needed_additional = max(0, target_fraud_count - existing_frauds)

        non_fraud_indices = df.loc[slice_indices][df.loc[slice_indices, "isFraud"] == 0].index
        if needed_additional > 0 and len(non_fraud_indices) > 0:
            flip_count = min(needed_additional, len(non_fraud_indices))
            flip_indices = rng.choice(non_fraud_indices, size=flip_count, replace=False)
            df.loc[flip_indices, "isFraud"] = 1
            after_frauds = int(df.loc[slice_indices, "isFraud"].sum())
        else:
            flip_count = 0
            after_frauds = existing_frauds

        after_rate = after_frauds / slice_total
        multiplier = after_rate / before_rate if before_rate > 0 else float("inf")

        record = {
            "spike_id": cfg["spike_id"],
            "start": cfg["start"],
            "end": cfg["end"],
            "region": target_region,
            "device": target_device,
            "type": target_type,
            "description": cfg["description"],
            "target_fraud_rate": target_rate,
            "total_transactions": int(slice_total),
            "before_fraud_count": int(existing_frauds),
            "before_fraud_rate": round(float(before_rate), 5),
            "injected_count": int(flip_count),
            "after_fraud_count": int(after_frauds),
            "after_fraud_rate": round(float(after_rate), 5),
            "multiplier": round(float(multiplier), 2) if multiplier != float("inf") else "inf",
        }
        ground_truth.append(record)
        summary_records.append(record)

    summary_df = pd.DataFrame(summary_records)[[
        "spike_id", "region", "device", "type", "start", "end",
        "total_transactions", "before_fraud_rate", "after_fraud_rate", "injected_count", "multiplier"
    ]]
    print("\nBefore / After Fraud Rate Summary by Injected Segment:")
    print(summary_df.to_string(index=False))

    print(f"\nSaving ground truth metadata to {ground_truth_path}...")
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ground_truth_path, "w") as f:
        json.dump(ground_truth, f, indent=2)
    print("Ground truth metadata saved.")

    print(f"Saving spiked dataset to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Spiked dataset successfully saved ({output_path.stat().st_size / (1024*1024):.1f} MB).")
    return df, ground_truth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to enriched PaySim CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for spiked PaySim CSV",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH_PATH,
        help="Path for ground truth JSON",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help="Random seed for reproducibility",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    inject_spikes(args.input, args.output, args.ground_truth, seed=args.seed)