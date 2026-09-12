import json
import os
import subprocess
import tempfile
import traceback

import joblib
import librosa
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request
from imageio_ffmpeg import get_ffmpeg_exe

from prediction_utils import build_prediction_result


APP = Flask(__name__)
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "output")
PREPROCESSOR_PATH = os.path.join(ARTIFACT_DIR, "preprocessor.joblib")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "model.joblib")


def load_artifacts():
    if not os.path.exists(PREPROCESSOR_PATH):
        raise FileNotFoundError(
            "Model artifacts not found. Run run_coughvid_local.py first to train and save the model."
        )
    preprocessor = joblib.load(PREPROCESSOR_PATH)
    expected_features = len(preprocessor.get_feature_names_out())
    candidate_paths = [MODEL_PATH] + [
        os.path.join(ARTIFACT_DIR, filename)
        for filename in ("random_forest.joblib", "extra_trees.joblib", "gradient_boosting.joblib")
    ]
    for model_path in candidate_paths:
        if not os.path.exists(model_path):
            continue
        model = joblib.load(model_path)
        if getattr(model, "n_features_in_", expected_features) == expected_features:
            if hasattr(model, "n_jobs"):
                model.n_jobs = 1
            return preprocessor, model
    raise ValueError(
        f"No compatible model found for the preprocessor's {expected_features} output features."
    )


def audio_to_mfcc(file_path, n_mfcc=20):
    try:
        y, sr = librosa.load(file_path, sr=None)
    except Exception:
        fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            ffmpeg_bin = get_ffmpeg_exe()
            ffmpeg_command = [
                ffmpeg_bin,
                "-y",
                "-i",
                file_path,
                "-acodec",
                "pcm_s16le",
                "-ar",
                "22050",
                tmp_wav,
            ]
            subprocess.run(ffmpeg_command, capture_output=True, check=True)
            if not os.path.exists(tmp_wav):
                raise RuntimeError("Could not convert audio file to WAV for MFCC extraction.")
            y, sr = librosa.load(tmp_wav, sr=None)
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    mfcc_mean = np.mean(mfcc, axis=1)
    mfcc_var = np.var(mfcc, axis=1)
    feature_dict = {}
    for i in range(n_mfcc):
        feature_dict[f"mfcc_{i+1}_mean"] = float(mfcc_mean[i])
        feature_dict[f"mfcc_{i+1}_var"] = float(mfcc_var[i])
    return feature_dict


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"Unable to parse boolean value: {value}")


def build_input_dataframe(data, preprocessor):
    numeric_cols = list(preprocessor.transformers_[0][2])
    categorical_cols = list(preprocessor.transformers_[1][2])

    expected_columns = numeric_cols + categorical_cols
    sample = {
        column: data.get(column, "unknown" if column in categorical_cols else 0.0)
        for column in expected_columns
    }
    sample["gender"] = str(sample["gender"]).strip().lower()
    sample["respiratory_condition"] = parse_bool(sample["respiratory_condition"])
    sample["fever_muscle_pain"] = parse_bool(sample["fever_muscle_pain"])
    sample["age"] = float(sample["age"])
    sample["cough_detected"] = float(sample["cough_detected"])

    df = pd.DataFrame([sample])
    return df


def predict_from_dataframe(df, preprocessor, model, notes="", respiratory_condition=False, fever_muscle_pain=False):
    X = preprocessor.transform(df)
    prediction = model.predict(X)[0]
    proba = model.predict_proba(X)[0]
    covid_proba = float(proba[1]) if len(proba) > 1 else 0.0
    healthy_proba = float(proba[0]) if len(proba) > 0 else 1.0 - covid_proba
    base_result = {
        "prediction": int(prediction),
        "status": "covid-19" if prediction == 1 else "healthy",
        "covid_probability": covid_proba,
        "healthy_probability": healthy_proba,
    }
    detail_result = build_prediction_result(
        prediction=prediction,
        probability=max(covid_proba, healthy_proba),
        notes=notes,
        respiratory_condition=parse_bool(respiratory_condition),
        fever_muscle_pain=parse_bool(fever_muscle_pain),
    )
    base_result.update(detail_result)
    return base_result


@APP.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@APP.route("/predict", methods=["POST"])
def predict():
    try:
        preprocessor, model = load_artifacts()
        payload = request.get_json(force=True)
        if payload is None:
            return jsonify({"error": "JSON body required."}), 400

        if "audio_file_path" in payload:
            audio_path = payload["audio_file_path"]
            if not os.path.exists(audio_path):
                return jsonify({"error": f"Audio file path does not exist: {audio_path}"}), 400
            mfcc_features = audio_to_mfcc(audio_path)
            payload.update(mfcc_features)

        df = build_input_dataframe(payload, preprocessor)
        notes = payload.get("notes", payload.get("manual_notes", ""))
        respiratory_condition = payload.get("respiratory_condition", False)
        fever_muscle_pain = payload.get("fever_muscle_pain", False)
        result = predict_from_dataframe(
            df,
            preprocessor,
            model,
            notes=notes,
            respiratory_condition=parse_bool(respiratory_condition),
            fever_muscle_pain=parse_bool(fever_muscle_pain),
        )
        return jsonify(result)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


@APP.route("/predict_audio", methods=["POST"])
def predict_audio():
    try:
        preprocessor, model = load_artifacts()
        if "audio" not in request.files:
            return jsonify({"error": "Audio file must be uploaded using the 'audio' form field."}), 400
        audio_file = request.files["audio"]
        if audio_file.filename == "":
            return jsonify({"error": "No audio file selected."}), 400

        metadata = {
            "gender": request.form.get("gender", "unknown"),
            "age": request.form.get("age", "30"),
            "cough_detected": request.form.get("cough_detected", "0.5"),
            "respiratory_condition": request.form.get("respiratory_condition", "false"),
            "fever_muscle_pain": request.form.get("fever_muscle_pain", "false"),
        }

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.filename)[1]) as temp_audio:
            audio_file.save(temp_audio.name)
        try:
            mfcc_features = audio_to_mfcc(temp_audio.name)
        finally:
            os.remove(temp_audio.name)

        metadata.update(mfcc_features)
        df = build_input_dataframe(metadata, preprocessor)
        result = predict_from_dataframe(
            df,
            preprocessor,
            model,
            notes=request.form.get("notes", ""),
            respiratory_condition=metadata.get("respiratory_condition", False),
            fever_muscle_pain=metadata.get("fever_muscle_pain", False),
        )
        return jsonify(result)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=5000, debug=True)
