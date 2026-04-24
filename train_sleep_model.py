"""
SleepSense AI — Sleep Stage Classification Model Training
==========================================================
Trains a Random Forest classifier on polysomnography data (ACC_X, ACC_Y, ACC_Z, HR)
to predict sleep stages (P, W, N1, N2, N3, R).

Uses only S002 and S006 datasets (the only ones with multi-class labels).

Usage:
    python train_sleep_model.py
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
DATA_DIR       = Path(__file__).parent
MODEL_PATH     = DATA_DIR / "sleep_model.joblib"
FEATURE_CFG    = DATA_DIR / "feature_config.json"
DATASETS       = ["compressed_S002_whole_df.csv", "compressed_S006_whole_df.csv"]
WINDOW_SIZE    = 64       # ~30 seconds at ~2 Hz sampling rate
VALID_STAGES   = {"P", "W", "N1", "N2", "N3", "R"}
RANDOM_STATE   = 42

# Sleep stage label mapping
STAGE_LABELS = {0: "P", 1: "W", 2: "N1", 3: "N2", 4: "N3", 5: "R"}


def load_and_clean(filepath: Path) -> pd.DataFrame:
    """Load a single CSV and clean it."""
    print(f"  Loading {filepath.name}...", end=" ")
    df = pd.read_csv(filepath, low_memory=False)

    # Drop unnamed columns (artifacts from CSV export)
    df = df[[c for c in df.columns if not c.startswith("Unnamed")]]

    # Remove any stray header rows embedded in data
    df = df[df["Sleep_Stage"] != "Sleep_Stage"]

    # Filter only valid sleep stages
    df = df[df["Sleep_Stage"].isin(VALID_STAGES)]

    # Convert numeric columns
    for col in ["TIMESTAMP", "ACC_X", "ACC_Y", "ACC_Z", "HR"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["ACC_X", "ACC_Y", "ACC_Z", "HR"])
    df = df.reset_index(drop=True)

    print(f"{len(df):,} rows, stages: {df['Sleep_Stage'].value_counts().to_dict()}")
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create rolling-window and derived features from raw sensor data."""
    print("  Engineering features...")
    feat = pd.DataFrame(index=df.index)

    # ── Raw features ──────────────────────────────────────────────────────
    feat["acc_x"] = df["ACC_X"].values
    feat["acc_y"] = df["ACC_Y"].values
    feat["acc_z"] = df["ACC_Z"].values
    feat["hr"]    = df["HR"].values

    # ── Derived: Acceleration magnitude ───────────────────────────────────
    feat["acc_mag"] = np.sqrt(
        df["ACC_X"].astype(float)**2 +
        df["ACC_Y"].astype(float)**2 +
        df["ACC_Z"].astype(float)**2
    )

    # ── Rolling window features ───────────────────────────────────────────
    window = WINDOW_SIZE

    for col in ["acc_x", "acc_y", "acc_z", "hr", "acc_mag"]:
        series = feat[col]
        feat[f"{col}_roll_mean"] = series.rolling(window, min_periods=1).mean()
        feat[f"{col}_roll_std"]  = series.rolling(window, min_periods=1).std().fillna(0)
        feat[f"{col}_roll_min"]  = series.rolling(window, min_periods=1).min()
        feat[f"{col}_roll_max"]  = series.rolling(window, min_periods=1).max()

    # ── Movement intensity (std of acc magnitude) ─────────────────────────
    feat["movement_intensity"] = feat["acc_mag"].rolling(window, min_periods=1).std().fillna(0)

    # ── HR delta (rate of change) ─────────────────────────────────────────
    feat["hr_delta"] = feat["hr"].diff().fillna(0)
    feat["hr_delta_roll_mean"] = feat["hr_delta"].rolling(window, min_periods=1).mean()

    # ── ACC range per axis ────────────────────────────────────────────────
    for axis in ["acc_x", "acc_y", "acc_z"]:
        feat[f"{axis}_roll_range"] = (
            feat[f"{axis}_roll_max"] - feat[f"{axis}_roll_min"]
        )

    # ── Lag features (previous 5 samples) ─────────────────────────────────
    for lag in [1, 2, 3, 5, 10]:
        feat[f"acc_mag_lag{lag}"] = feat["acc_mag"].shift(lag).fillna(feat["acc_mag"].iloc[0])
        feat[f"hr_lag{lag}"]     = feat["hr"].shift(lag).fillna(feat["hr"].iloc[0])

    # ── Zero-crossing rate (proxy for vibration/movement) ─────────────────
    for axis in ["acc_x", "acc_y", "acc_z"]:
        sign_changes = (feat[axis].diff().fillna(0) != 0).astype(int)
        feat[f"{axis}_zcr"] = sign_changes.rolling(window, min_periods=1).sum()

    print(f"    → {feat.shape[1]} features generated")
    return feat


def main():
    print("\n" + "═" * 60)
    print("  SleepSense AI — Model Training Pipeline")
    print("═" * 60 + "\n")

    # ── Step 1: Load data ─────────────────────────────────────────────────
    print("Step 1: Loading datasets")
    dfs = []
    for fname in DATASETS:
        fpath = DATA_DIR / fname
        if fpath.exists():
            dfs.append(load_and_clean(fpath))
        else:
            print(f"  ⚠️  Skipping {fname} — file not found")

    if not dfs:
        print("  ❌ No data files found. Exiting.")
        return

    combined = pd.concat(dfs, ignore_index=True)
    print(f"\n  Combined dataset: {len(combined):,} rows")
    print(f"  Stage distribution:\n{combined['Sleep_Stage'].value_counts().to_string()}\n")

    # ── Step 2: Feature engineering ───────────────────────────────────────
    print("Step 2: Feature engineering")
    features = engineer_features(combined)
    labels   = combined["Sleep_Stage"].values

    # Encode labels
    le = LabelEncoder()
    le.fit(sorted(VALID_STAGES))
    y = le.transform(labels)

    # Feature names for later use
    feature_names = features.columns.tolist()

    X = features.values.astype(np.float32)
    print(f"  Feature matrix: {X.shape}")
    print(f"  Labels: {len(y)} ({len(np.unique(y))} classes: {le.classes_.tolist()})")

    # ── Step 3: Train/test split ──────────────────────────────────────────
    print("\nStep 3: Train/test split (80/20 stratified)")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    print(f"  Train: {X_train.shape[0]:,}  |  Test: {X_test.shape[0]:,}")

    # ── Step 4: Train model ───────────────────────────────────────────────
    print("\nStep 4: Training Random Forest classifier...")
    t0 = time.time()

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=25,
        min_samples_split=10,
        min_samples_leaf=4,
        class_weight="balanced",
        n_jobs=-1,
        random_state=RANDOM_STATE,
        verbose=0,
    )
    model.fit(X_train, y_train)
    train_time = time.time() - t0
    print(f"  ✅ Training complete in {train_time:.1f}s")

    # ── Step 5: Evaluate ──────────────────────────────────────────────────
    print("\nStep 5: Evaluation on test set")
    y_pred = model.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"\n  Overall Accuracy: {acc:.4f} ({acc*100:.1f}%)\n")

    target_names = le.classes_.tolist()
    print("  Classification Report:")
    print("  " + "-" * 58)
    report = classification_report(y_test, y_pred, target_names=target_names)
    for line in report.split("\n"):
        print(f"  {line}")

    print("\n  Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    header = "        " + "  ".join(f"{s:>5}" for s in target_names)
    print(f"  {header}")
    for i, row in enumerate(cm):
        row_str = "  ".join(f"{v:>5}" for v in row)
        print(f"  {target_names[i]:>5}:  {row_str}")

    # ── Feature importance ────────────────────────────────────────────────
    print("\n  Top 15 Feature Importances:")
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1][:15]
    for rank, idx in enumerate(sorted_idx, 1):
        print(f"    {rank:>2}. {feature_names[idx]:<25} {importances[idx]:.4f}")

    # ── Step 6: Save model ────────────────────────────────────────────────
    print(f"\nStep 6: Saving model")

    # Save the model + label encoder together
    artifact = {
        "model": model,
        "label_encoder": le,
        "feature_names": feature_names,
        "window_size": WINDOW_SIZE,
        "valid_stages": sorted(list(VALID_STAGES)),
        "accuracy": float(acc),
    }
    joblib.dump(artifact, MODEL_PATH)
    print(f"  ✅ Model saved to: {MODEL_PATH}")
    print(f"     File size: {MODEL_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    # Save feature config (used by real-time predictor)
    feature_config = {
        "feature_names": feature_names,
        "window_size": WINDOW_SIZE,
        "raw_columns": ["ACC_X", "ACC_Y", "ACC_Z", "HR"],
        "stage_labels": {int(k): v for k, v in STAGE_LABELS.items()},
        "stage_colors": {
            "P":  "#6366f1",   # indigo
            "W":  "#f59e0b",   # amber
            "N1": "#22d3ee",   # cyan
            "N2": "#3b82f6",   # blue
            "N3": "#8b5cf6",   # violet
            "R":  "#ef4444",   # red
        },
    }
    with open(FEATURE_CFG, "w") as f:
        json.dump(feature_config, f, indent=2)
    print(f"  ✅ Feature config saved to: {FEATURE_CFG}")

    print("\n" + "═" * 60)
    print("  Training complete!")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
