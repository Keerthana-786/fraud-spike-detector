"""Train a separate live-compatible model using only fields available from normalized Razorpay payments."""
from __future__ import annotations

from pathlib import Path
import sys
import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.live_pipeline import LIVE_MODEL_PATH

INPUT_PATH = PROJECT_ROOT / "data" / "paysim_spiked.csv"


def train_live_model(
    input_path: Path = INPUT_PATH,
    output_path: Path = LIVE_MODEL_PATH,
    max_negative_rows: int = 500_000,
) -> Path:
    """Train live-compatible XGBoost model on amount, hour_of_day, and payment methods."""
    sample_chunks = []
    for chunk in pd.read_csv(input_path, usecols=["timestamp", "amount", "type", "isFraud"], chunksize=500_000):
        pos = chunk[chunk["isFraud"] == 1]
        neg = chunk[chunk["isFraud"] == 0].sample(min(40_000, int((chunk["isFraud"] == 0).sum())), random_state=42)
        sample_chunks.append(pd.concat([pos, neg]))

    df = pd.concat(sample_chunks, ignore_index=True)
    timestamps = pd.to_datetime(df["timestamp"])

    types = df["type"].astype(str)
    is_payment = (types == "PAYMENT")

    np.random.seed(42)
    rand_methods = np.random.choice(["card", "upi", "netbanking", "wallet"], size=len(df), p=[0.45, 0.35, 0.12, 0.08])
    actual_methods = np.where(is_payment, rand_methods, "other")

    features = pd.DataFrame({
        "amount": df["amount"].astype(np.float32),
        "hour_of_day": timestamps.dt.hour.astype(np.int8),
        "method_card": (actual_methods == "card").astype(np.float32),
        "method_upi": (actual_methods == "upi").astype(np.float32),
        "method_netbanking": (actual_methods == "netbanking").astype(np.float32),
        "method_wallet": (actual_methods == "wallet").astype(np.float32),
        "method_other": (actual_methods == "other").astype(np.float32),
    })

    pos_cnt = int(df["isFraud"].sum())
    neg_cnt = len(df) - pos_cnt

    model = XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=10.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features, df["isFraud"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_path)
    return output_path


if __name__ == "__main__":
    print(f"Saved live-compatible model to {train_live_model()}")
