"""Synthesize categorical dimensions and real timestamp for PaySim dataset."""

from pathlib import Path
import argparse
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "paysim.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "paysim_enriched.csv"

# Reproducibility seed
SEED = 42

# Category definitions and weights
REGIONS = ["North", "South", "East", "West"]
REGION_PROBS = [0.35, 0.25, 0.20, 0.20]

DEVICES = ["mobile", "web", "pos", "atm"]
DEVICE_PROBS = [0.50, 0.25, 0.15, 0.10]

START_DATE = "2024-01-01 00:00:00"


def synthesize_dimensions(input_path: Path, output_path: Path, seed: int = SEED) -> pd.DataFrame:
    """Enrich PaySim dataset with synthetic region, device, and timestamp."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input dataset not found: {input_path}")

    print(f"Loading raw data from {input_path}...")
    df = pd.read_csv(input_path)
    n_rows = len(df)
    print(f"Loaded {n_rows:,} rows.")

    rng = np.random.default_rng(seed)

    print("Synthesizing 'region' and 'device' dimensions...")
    df["region"] = rng.choice(REGIONS, size=n_rows, p=REGION_PROBS)
    df["device"] = rng.choice(DEVICES, size=n_rows, p=DEVICE_PROBS)

    print("Converting 'step' into datetime 'timestamp' starting 2024-01-01...")
    start_timestamp = pd.Timestamp(START_DATE)
    # step is 1-indexed (1 step = 1 hour)
    df["timestamp"] = start_timestamp + pd.to_timedelta(df["step"] - 1, unit="h")

    print(f"\nSynthetic Dimension Summary:")
    print("Region distribution:")
    print(df["region"].value_counts(normalize=True).round(4) * 100)
    print("\nDevice distribution:")
    print(df["device"].value_counts(normalize=True).round(4) * 100)
    print(f"\nTimestamp range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    print(f"\nSaving enriched dataset to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Enriched dataset successfully saved ({output_path.stat().st_size / (1024*1024):.1f} MB).")
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to raw PaySim CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for enriched PaySim CSV",
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
    synthesize_dimensions(args.input, args.output, seed=args.seed)