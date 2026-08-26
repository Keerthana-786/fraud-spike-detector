"""Load and inspect the PaySim fraud dataset."""

from pathlib import Path
import argparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "paysim.csv"


def load_and_inspect(data_path: Path) -> pd.DataFrame:
    """Load the CSV and print its shape, schema, class balance, and summaries."""
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    dataframe = pd.read_csv(data_path)

    print(f"Shape: {dataframe.shape}")
    print("\nDtypes:")
    print(dataframe.dtypes)

    if "isFraud" not in dataframe.columns:
        raise KeyError("Expected an 'isFraud' column in the dataset")

    fraud_counts = dataframe["isFraud"].value_counts(dropna=False).sort_index()
    fraud_percentages = (
        dataframe["isFraud"].value_counts(normalize=True, dropna=False).sort_index() * 100
    )
    class_balance = pd.DataFrame(
        {"count": fraud_counts, "percentage": fraud_percentages.round(4)}
    )
    print("\nClass balance (isFraud):")
    print(class_balance)

    print("\nBasic summary statistics:")
    print(dataframe.describe(include="all"))

    return dataframe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Path to the PaySim CSV (default: ./data/paysim.csv)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    load_and_inspect(args.data_path)
