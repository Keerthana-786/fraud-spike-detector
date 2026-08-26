"""Train an XGBoost fraud classifier with a time-based split and score transactions."""

from pathlib import Path
import argparse
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "paysim_spiked.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "paysim_scored.csv"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "xgb_fraud_model.joblib"


def build_features(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Engineer balance delta, time, and categorical features for XGBoost."""
    required = {
        "amount",
        "type",
        "oldbalanceOrg",
        "newbalanceOrig",
        "oldbalanceDest",
        "newbalanceDest",
        "isFraud",
        "timestamp",
    }
    missing = sorted(required - set(dataframe.columns))
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(missing)}")

    timestamps = pd.to_datetime(dataframe["timestamp"])

    features = pd.DataFrame(index=dataframe.index)
    features["amount"] = dataframe["amount"].astype(np.float32)
    features["oldbalanceOrg"] = dataframe["oldbalanceOrg"].astype(np.float32)
    features["newbalanceOrig"] = dataframe["newbalanceOrig"].astype(np.float32)
    features["oldbalanceDest"] = dataframe["oldbalanceDest"].astype(np.float32)
    features["newbalanceDest"] = dataframe["newbalanceDest"].astype(np.float32)
    features["orig_balance_delta"] = (
        dataframe["newbalanceOrig"] - dataframe["oldbalanceOrg"]
    ).astype(np.float32)
    features["dest_balance_delta"] = (
        dataframe["newbalanceDest"] - dataframe["oldbalanceDest"]
    ).astype(np.float32)
    features["hour_of_day"] = timestamps.dt.hour.astype(np.int8)

    # One-hot encode transaction type
    type_dummies = pd.get_dummies(dataframe["type"], prefix="type", dtype=np.float32)
    features = pd.concat([features, type_dummies], axis=1)

    return features, timestamps


def train_and_score(
    input_path: Path,
    output_path: Path,
    model_path: Path,
    train_ratio: float = 0.8,
    scale_pos_weight: float = 10.0,
) -> tuple[XGBClassifier, pd.DataFrame]:
    """Train XGBoost on chronological train split, evaluate on test split, score dataset."""
    if not input_path.exists():
        raise FileNotFoundError(f"Spiked dataset not found: {input_path}")

    print(f"Loading spiked dataset from {input_path}...")
    df = pd.read_csv(input_path)
    n_rows = len(df)
    print(f"Loaded {n_rows:,} rows. Engineering features...")

    features, timestamps = build_features(df)
    print(f"Features engineered: {list(features.columns)}")

    # Time-based train / test split
    time_sorted_idx = timestamps.sort_values(kind="stable").index
    split_idx = int(n_rows * train_ratio)
    train_indices = time_sorted_idx[:split_idx]
    test_indices = time_sorted_idx[split_idx:]

    print(f"\nTime-Based Split ({int(train_ratio*100)}/{int((1-train_ratio)*100)}):")
    print(f"Train transactions: {len(train_indices):,} (Range: {timestamps.loc[train_indices].min()} to {timestamps.loc[train_indices].max()})")
    print(f"Test transactions:  {len(test_indices):,} (Range: {timestamps.loc[test_indices].min()} to {timestamps.loc[test_indices].max()})")

    X_train = features.loc[train_indices]
    y_train = df.loc[train_indices, "isFraud"]
    X_test = features.loc[test_indices]
    y_test = df.loc[test_indices, "isFraud"]

    pos_count = int(y_train.sum())
    neg_count = int(len(y_train) - pos_count)

    print(f"\nTrain class distribution: {pos_count:,} frauds ({pos_count/len(y_train)*100:.4f}%), {neg_count:,} non-frauds")
    print(f"Test class distribution:  {int(y_test.sum()):,} frauds ({y_test.mean()*100:.4f}%)")
    print(f"Using scale_pos_weight:   {scale_pos_weight:.2f}")

    print("\nTraining XGBoost Classifier (tree_method='hist')...")
    model = XGBClassifier(
        n_estimators=150,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    print("XGBoost training complete.")

    # Evaluate on holdout test set
    print("\n--- Test Set Evaluation ---")
    test_probs = model.predict_proba(X_test)[:, 1]
    test_preds = (test_probs >= 0.5).astype(int)

    precision = precision_score(y_test, test_preds, zero_division=0)
    recall = recall_score(y_test, test_preds, zero_division=0)
    f1 = f1_score(y_test, test_preds, zero_division=0)
    auc = roc_auc_score(y_test, test_probs)

    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1 Score:  {f1:.4f}")
    print(f"ROC-AUC:   {auc:.4f}")

    # Generate fraud probability for all transactions in batches to conserve memory
    print("\nScoring full dataset (generating fraud_prob)...")
    batch_size = 500_000
    probs = np.empty(n_rows, dtype=np.float32)
    for start in range(0, n_rows, batch_size):
        end = min(start + batch_size, n_rows)
        probs[start:end] = model.predict_proba(features.iloc[start:end])[:, 1]

    df["fraud_prob"] = probs

    # Save model artifact for SHAP explainability in Phase 5
    print(f"Saving trained model to {model_path}...")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)

    # Save scored dataset
    print(f"Saving scored transactions to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Scored dataset saved ({output_path.stat().st_size / (1024*1024):.1f} MB).")

    return model, df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--scale-pos-weight", type=float, default=10.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train_and_score(
        args.input,
        args.output,
        args.model,
        args.train_ratio,
        args.scale_pos_weight,
    )