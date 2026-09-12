#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import traceback

import joblib
import numpy as np
import pandas as pd
from imageio_ffmpeg import get_ffmpeg_exe
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.ensemble import (
    RandomForestClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    AdaBoostClassifier,
    BaggingClassifier,
)
from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import accuracy_score

from run_coughvid_local import load_metadata, clean_metadata, extract_audio_features, extract_mfcc_features


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def build_preprocessor_and_features(df, output_dir, n_mfcc=20):
    target_map = {"healthy": 0, "covid-19": 1}
    df = df[df["status"].isin(target_map)].copy()
    if df.empty:
        raise ValueError("No rows with status 'healthy' or 'covid-19' available for modeling.")

    df["target"] = df["status"].map(target_map)
    X = df.drop(columns=["file_id", "status", "target", "datetime", "latitude", "longitude"], errors="ignore")
    y = df["target"]

    numeric_cols = X.select_dtypes(include=[np.number, bool]).columns.tolist()
    categorical_cols = ["gender"] if "gender" in X.columns else []

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), numeric_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
        ],
        remainder="drop",
    )

    X_processed = preprocessor.fit_transform(X)

    os.makedirs(output_dir, exist_ok=True)
    preprocessor_path = os.path.join(output_dir, "preprocessor.joblib")
    joblib.dump(preprocessor, preprocessor_path)
    logging.info("Saved preprocessor to %s", preprocessor_path)

    return X_processed, y


def train_and_save_models(X, y, output_dir, random_state=42):
    models = {
        "random_forest": RandomForestClassifier(n_estimators=100, class_weight="balanced", random_state=random_state, n_jobs=1),
        "extra_trees": ExtraTreesClassifier(n_estimators=100, class_weight="balanced", random_state=random_state, n_jobs=1),
        "gradient_boosting": GradientBoostingClassifier(random_state=random_state),
        "adaboost": AdaBoostClassifier(random_state=random_state),
        "bagging": BaggingClassifier(random_state=random_state),
        "decision_tree": DecisionTreeClassifier(random_state=random_state),
        "knn": KNeighborsClassifier(),
        "svc": SVC(probability=True, random_state=random_state),
        "logistic": LogisticRegression(max_iter=1000, random_state=random_state),
        "sgd": SGDClassifier(loss='log_loss', max_iter=1000, random_state=random_state),
    }

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, stratify=y, random_state=random_state)

    results = {}
    for name, clf in models.items():
        logging.info("Training %s", name)
        try:
            clf.fit(X_train, y_train)
            preds = clf.predict(X_test)
            acc = accuracy_score(y_test, preds)
            model_path = os.path.join(output_dir, f"{name}.joblib")
            joblib.dump(clf, model_path)
            logging.info("Saved %s to %s (acc %.4f)", name, model_path, acc)
            results[name] = {"path": model_path, "accuracy": float(acc)}
        except Exception as exc:
            logging.error("Failed to train %s: %s", name, exc)
            results[name] = {"path": None, "error": str(exc)}

    summary_path = os.path.join(output_dir, "models_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logging.info("Wrote models summary to %s", summary_path)
    return results


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Train multiple models for cough detection and save artifacts.")
    parser.add_argument("--dataset-dir", default="public_dataset", help="Path to dataset")
    parser.add_argument("--output-dir", default="output", help="Directory to save models")
    parser.add_argument("--mfcc-count", type=int, default=20, help="MFCC count")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files to process")
    args = parser.parse_args()

    try:
        dataset_dir = os.path.abspath(args.dataset_dir)
        output_dir = os.path.abspath(args.output_dir)
        logging.info("Using dataset: %s", dataset_dir)

        metadata_df = load_metadata(dataset_dir)
        metadata_df = clean_metadata(metadata_df)

        audio_features_df = extract_audio_features(metadata_df, dataset_dir, n_mfcc=args.mfcc_count, limit=args.limit)
        if audio_features_df.empty:
            raise RuntimeError("No audio features extracted; check audio files and ffmpeg.")

        merged_df = metadata_df.merge(audio_features_df, on="file_id", how="inner")
        logging.info("Merged metadata and MFCC features: %d rows", len(merged_df))

        X, y = build_preprocessor_and_features(merged_df, output_dir, n_mfcc=args.mfcc_count)
        train_and_save_models(X, y, output_dir)
        logging.info("Training completed.")
    except Exception as exc:
        logging.error("Training failed: %s", exc)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
