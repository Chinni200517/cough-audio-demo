#!/usr/bin/env python3
import argparse
import json
import logging
import os
import subprocess
import sys
import traceback

import joblib
import librosa
import numpy as np
import pandas as pd
from imageio_ffmpeg import get_ffmpeg_exe
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from tqdm import tqdm


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_metadata(dataset_dir):
    metadata_rows = []
    if not os.path.isdir(dataset_dir):
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    for filename in sorted(os.listdir(dataset_dir)):
        if filename.endswith(".json"):
            file_path = os.path.join(dataset_dir, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                metadata["file_id"] = os.path.splitext(filename)[0]
                metadata_rows.append(metadata)
            except Exception as exc:
                logging.warning("Skipping JSON file %s due to error: %s", filename, exc)

    if not metadata_rows:
        raise ValueError(f"No metadata JSON files found in {dataset_dir}")

    df = pd.DataFrame(metadata_rows)
    logging.info("Loaded %d metadata records from %s", len(df), dataset_dir)
    return df


def normalize_gender_status(df):
    for col in ["gender", "status"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower().replace({"nan": None})
        else:
            df[col] = None
    return df


def clean_metadata(df):
    df = df.copy()
    df = normalize_gender_status(df)

    numeric_columns = ["cough_detected", "latitude", "longitude", "age"]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    df["age"] = df["age"].fillna(df["age"].median(skipna=True))

    for col in ["respiratory_condition", "fever_muscle_pain"]:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False, True: True, False: False}).fillna(False).astype(bool)
        else:
            df[col] = False

    df["gender"] = df["gender"].fillna("unknown").astype("category")
    df["status"] = df["status"].fillna("unknown").astype("category")

    return df


def find_audio_file(file_id, dataset_dir):
    extensions = [".webm", ".wav", ".ogg", ".mp3", ".m4a"]
    for ext in extensions:
        candidate = os.path.join(dataset_dir, f"{file_id}{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


def convert_to_wav(input_path, output_path):
    ffmpeg_bin = get_ffmpeg_exe()
    command = [ffmpeg_bin, "-y", "-i", input_path, "-acodec", "pcm_s16le", "-ar", "22050", output_path]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=60)
        return output_path
    except subprocess.CalledProcessError as exc:
        logging.warning("ffmpeg conversion failed for %s: %s", input_path, exc.stderr.decode(errors="replace"))
        return None
    except Exception as exc:
        logging.warning("ffmpeg conversion error for %s: %s", input_path, exc)
        return None


def load_audio_file(audio_path, temp_dir):
    try:
        return librosa.load(audio_path, sr=None)
    except Exception:
        logging.debug("Direct librosa load failed for %s", audio_path)
        output_path = os.path.join(temp_dir, os.path.splitext(os.path.basename(audio_path))[0] + ".wav")
        converted = convert_to_wav(audio_path, output_path)
        if converted and os.path.exists(converted):
            try:
                return librosa.load(converted, sr=None)
            except Exception as exc:
                logging.warning("Failed to load converted WAV %s: %s", converted, exc)
        return None, None


def extract_audio_features(df, dataset_dir, n_mfcc=20, limit=None):
    features = []
    temp_dir = os.path.join(dataset_dir, "_temp_audio")
    os.makedirs(temp_dir, exist_ok=True)

    rows = df.itertuples(index=False)
    if limit is not None:
        rows = list(df.itertuples(index=False))[:limit]

    for row in tqdm(rows, desc="Extracting audio features", unit="file"):
        file_id = getattr(row, "file_id", None)
        if not file_id:
            continue

        audio_path = find_audio_file(file_id, dataset_dir)
        if audio_path is None:
            logging.debug("Missing audio file for file_id=%s", file_id)
            continue

        y, sr = load_audio_file(audio_path, temp_dir)
        if y is None or sr is None:
            continue

        try:
            record = {"file_id": file_id}
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_var = np.var(mfcc, axis=1)
            record.update({f"mfcc_{i+1}_mean": float(mfcc_mean[i]) for i in range(n_mfcc)})
            record.update({f"mfcc_{i+1}_var": float(mfcc_var[i]) for i in range(n_mfcc)})

            zcr = librosa.feature.zero_crossing_rate(y)
            record["zero_crossing_rate_mean"] = float(np.mean(zcr))
            record["zero_crossing_rate_var"] = float(np.var(zcr))

            centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
            record["spectral_centroid_mean"] = float(np.mean(centroid))
            record["spectral_centroid_var"] = float(np.var(centroid))

            bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
            record["spectral_bandwidth_mean"] = float(np.mean(bandwidth))
            record["spectral_bandwidth_var"] = float(np.var(bandwidth))

            rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
            record["spectral_rolloff_mean"] = float(np.mean(rolloff))
            record["spectral_rolloff_var"] = float(np.var(rolloff))

            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
            record["chroma_mean"] = float(np.mean(chroma))
            record["chroma_var"] = float(np.var(chroma))

            rms = librosa.feature.rms(y=y)
            record["rms_mean"] = float(np.mean(rms))
            record["rms_var"] = float(np.var(rms))

            features.append(record)
        except Exception as exc:
            logging.warning("Failed to extract audio features for %s: %s", file_id, exc)

    for temp_file in os.listdir(temp_dir):
        try:
            os.remove(os.path.join(temp_dir, temp_file))
        except Exception:
            pass

    if features:
        columns = ["file_id"] + [f"mfcc_{i+1}_mean" for i in range(n_mfcc)] + [f"mfcc_{i+1}_var" for i in range(n_mfcc)] + [
            "zero_crossing_rate_mean", "zero_crossing_rate_var",
            "spectral_centroid_mean", "spectral_centroid_var",
            "spectral_bandwidth_mean", "spectral_bandwidth_var",
            "spectral_rolloff_mean", "spectral_rolloff_var",
            "chroma_mean", "chroma_var",
            "rms_mean", "rms_var",
        ]
        return pd.DataFrame(features, columns=columns)

    return pd.DataFrame(columns=["file_id"] + [f"mfcc_{i+1}_mean" for i in range(n_mfcc)] + [f"mfcc_{i+1}_var" for i in range(n_mfcc)] + [
        "zero_crossing_rate_mean", "zero_crossing_rate_var",
        "spectral_centroid_mean", "spectral_centroid_var",
        "spectral_bandwidth_mean", "spectral_bandwidth_var",
        "spectral_rolloff_mean", "spectral_rolloff_var",
        "chroma_mean", "chroma_var",
        "rms_mean", "rms_var",
    ])


def extract_mfcc_features(df, dataset_dir, n_mfcc=20, limit=None):
    features = []
    temp_dir = os.path.join(dataset_dir, "_temp_audio")
    os.makedirs(temp_dir, exist_ok=True)

    rows = df.itertuples(index=False)
    if limit is not None:
        rows = list(df.itertuples(index=False))[:limit]

    for row in tqdm(rows, desc="Extracting MFCCs", unit="file"):
        file_id = getattr(row, "file_id", None)
        if not file_id:
            continue

        audio_path = find_audio_file(file_id, dataset_dir)
        if audio_path is None:
            logging.debug("Missing audio file for file_id=%s", file_id)
            continue

        y, sr = load_audio_file(audio_path, temp_dir)
        if y is None or sr is None:
            continue

        try:
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_var = np.var(mfcc, axis=1)
            record = {"file_id": file_id}
            record.update({f"mfcc_{i+1}_mean": float(mfcc_mean[i]) for i in range(n_mfcc)})
            record.update({f"mfcc_{i+1}_var": float(mfcc_var[i]) for i in range(n_mfcc)})
            features.append(record)
        except Exception as exc:
            logging.warning("Failed to extract MFCCs for %s: %s", file_id, exc)

    # Cleanup temporary converted audio files
    for temp_file in os.listdir(temp_dir):
        try:
            os.remove(os.path.join(temp_dir, temp_file))
        except Exception:
            pass

    if features:
        return pd.DataFrame(features)
    return pd.DataFrame(columns=["file_id"] + [f"mfcc_{i+1}_mean" for i in range(n_mfcc)] + [f"mfcc_{i+1}_var" for i in range(n_mfcc)])


def build_model(df, output_dir, random_state=42):
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

    model = RandomForestClassifier(
        n_estimators=100,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_processed, y)

    X_train, X_test, y_train, y_test = train_test_split(
        X_processed, y, test_size=0.20, stratify=y, random_state=random_state
    )
    model.fit(X_train, y_train)
    score = model.score(X_test, y_test)
    logging.info("Model accuracy on hold-out test set: %.4f", score)

    os.makedirs(output_dir, exist_ok=True)
    preprocessor_path = os.path.join(output_dir, "preprocessor.joblib")
    model_path = os.path.join(output_dir, "model.joblib")
    joblib.dump(preprocessor, preprocessor_path)
    joblib.dump(model, model_path)
    logging.info("Saved preprocessor to %s", preprocessor_path)
    logging.info("Saved model to %s", model_path)
    return preprocessor_path, model_path


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Local COVID cough detection pipeline for the Coughvid dataset.")
    parser.add_argument(
        "--dataset-dir",
        default="public_dataset",
        help="Path to the local dataset directory containing .json and audio files.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to save preprocessor and model artifacts.",
    )
    parser.add_argument(
        "--mfcc-count",
        type=int,
        default=20,
        help="Number of MFCC coefficients to extract.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of audio files processed (useful for quick local tests).",
    )
    args = parser.parse_args()

    try:
        dataset_dir = os.path.abspath(args.dataset_dir)
        logging.info("Using dataset directory: %s", dataset_dir)

        metadata_df = load_metadata(dataset_dir)
        metadata_df = clean_metadata(metadata_df)

        mfcc_df = extract_mfcc_features(metadata_df, dataset_dir, n_mfcc=args.mfcc_count, limit=args.limit)
        if mfcc_df.empty:
            raise RuntimeError("No MFCC features were extracted. Please verify the audio files and ffmpeg installation.")

        merged_df = metadata_df.merge(mfcc_df, on="file_id", how="inner")
        logging.info("Merged metadata and MFCC features: %d rows", len(merged_df))

        if merged_df.empty:
            raise RuntimeError("No merged records remain after joining metadata and MFCC features.")

        build_model(merged_df, os.path.abspath(args.output_dir))
        logging.info("Pipeline completed successfully.")
    except Exception as exc:
        logging.error("Pipeline failed: %s", exc)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
