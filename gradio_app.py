import os
import json
import subprocess
import tempfile
import traceback
from html import escape

import argparse
import requests
import joblib
import gradio as gr
import numpy as np
import pandas as pd
import soundfile as sf
from scipy.fft import dct
from imageio_ffmpeg import get_ffmpeg_exe

from prediction_utils import build_prediction_result
from frontend_ui import APP_CSS, build_app

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "output")
PREPROCESSOR_PATH = os.path.join(ARTIFACT_DIR, "preprocessor.joblib")
N_MFCC = 20


def load_preprocessor():
    if not os.path.exists(PREPROCESSOR_PATH):
        raise FileNotFoundError(
            "Preprocessor artifact not found. Run training first to create output/preprocessor.joblib."
        )
    return joblib.load(PREPROCESSOR_PATH)


def list_available_models():
    # look for model_*.joblib, or fallback to model.joblib
    models = []
    if not os.path.isdir(ARTIFACT_DIR):
        return models
    for fname in sorted(os.listdir(ARTIFACT_DIR)):
        if fname.endswith(".joblib") and fname != os.path.basename(PREPROCESSOR_PATH):
            models.append(fname)
    return models


def compatible_model_files(preprocessor, model_files):
    expected_features = len(preprocessor.get_feature_names_out())
    compatible = []
    for filename in model_files:
        model_path = os.path.join(ARTIFACT_DIR, filename)
        try:
            model = joblib.load(model_path)
            if getattr(model, "n_features_in_", expected_features) == expected_features:
                compatible.append(filename)
        except Exception:
            continue
    return compatible


def choose_best_model(model_files):
    summary_path = os.path.join(ARTIFACT_DIR, "models_summary.json")
    scores = {}
    try:
        with open(summary_path, "r", encoding="utf-8") as summary_file:
            summary = json.load(summary_file)
        scores = {
            f"{name}.joblib": float(details["accuracy"])
            for name, details in summary.items()
            if details.get("path") and "accuracy" in details
        }
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return max(model_files, key=lambda filename: scores.get(filename, -1), default="")


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "t", "on"}:
        return True
    if text in {"false", "0", "no", "n", "f", "off"}:
        return False
    raise ValueError(f"Unable to parse boolean value: {value}")


def convert_audio_to_wav(input_path):
    tmpfd, output_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmpfd)
    ffmpeg_bin = get_ffmpeg_exe()
    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        input_path,
        "-acodec",
        "pcm_s16le",
        "-ar",
        "22050",
        output_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(output_path):
        return output_path
    raise RuntimeError(
        f"ffmpeg failed to convert the uploaded audio file. stderr={result.stderr}"
    )


def read_audio_samples(audio_path, max_seconds=30):
    """Return mono float audio, sample rate, and a temporary conversion path."""
    converted_path = None
    source_path = os.fspath(audio_path)
    if os.path.splitext(source_path)[1].lower() not in {".wav", ".flac", ".ogg"}:
        converted_path = convert_audio_to_wav(source_path)
        source_path = converted_path
    try:
        y, sr = sf.read(source_path, dtype="float32", always_2d=False)
    except Exception:
        converted_path = convert_audio_to_wav(source_path)
        y, sr = sf.read(converted_path, dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        raise ValueError("The audio recording is empty.")
    y = np.nan_to_num(y)
    if max_seconds and y.size > int(sr * max_seconds):
        y = y[: int(sr * max_seconds)]
    return y, int(sr), converted_path


def validate_audio_quality(audio_path):
    y, sr, converted_path = read_audio_samples(audio_path, max_seconds=30)
    try:
        duration = len(y) / sr
        rms = float(np.sqrt(np.mean(y**2)))
        dbfs = float(20 * np.log10(max(rms, 1e-8)))
        peak = float(np.max(np.abs(y)))
        clipping_ratio = float(np.mean(np.abs(y) >= 0.99))
        frame_size = max(1, int(sr * 0.05))
        usable = y[: len(y) - (len(y) % frame_size)]
        if usable.size:
            frame_rms = np.sqrt(np.mean(usable.reshape(-1, frame_size) ** 2, axis=1))
            silence_ratio = float(np.mean(frame_rms < 0.004))
        else:
            silence_ratio = 1.0
        issues = []
        if duration < 0.7:
            issues.append("Recording is too short; capture at least one clear cough.")
        if rms < 0.003:
            issues.append("Signal is nearly silent; move closer to the microphone.")
        if clipping_ratio > 0.02:
            issues.append("Audio is clipping; move slightly away from the microphone.")
        if silence_ratio > 0.9:
            issues.append("Most of the recording is silence.")
        if duration > 25:
            issues.append("Only the first 30 seconds were analysed.")
        blocking = duration < 0.35 or rms < 0.0005
        status = "poor" if blocking else ("review" if issues else "good")
        return {
            "status": status, "blocking": blocking, "duration": duration,
            "rms": rms, "dbfs": dbfs, "peak": peak,
            "clipping_ratio": clipping_ratio, "silence_ratio": silence_ratio,
            "issues": issues,
        }
    finally:
        if converted_path and os.path.exists(converted_path):
            try:
                os.remove(converted_path)
            except OSError:
                pass


def quality_html(quality):
    issues = quality.get("issues") or ["Recording length and signal level are suitable for screening."]
    issue_items = "".join(f"<li>{escape(str(item))}</li>" for item in issues)
    return f'''<div class="quality-card quality-{escape(quality['status'])}">
      <div class="section-label">Recording quality · {escape(quality['status'].upper())}</div>
      <div class="quality-stats"><span>{quality['duration']:.1f}s duration</span><span>{quality['dbfs']:.1f} dBFS signal</span><span>{quality['clipping_ratio'] * 100:.2f}% clipping</span></div>
      <ul>{issue_items}</ul></div>'''


def model_probability(model, X):
    if hasattr(model, "n_jobs"):
        model.n_jobs = 1
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(X)[0], dtype=float)
        classes = np.asarray(getattr(model, "classes_", np.arange(len(proba))))
        index = int(np.argmax(proba))
        return classes[index], float(proba[index]), float(proba[1] if len(proba) > 1 else proba[index])
    score = float(np.ravel(model.decision_function(X))[0])
    disease_probability = float(1.0 / (1.0 + np.exp(-score)))
    prediction = 1 if disease_probability >= 0.5 else 0
    return prediction, max(disease_probability, 1 - disease_probability), disease_probability


def compare_models(X, model_files):
    summary_path = os.path.join(ARTIFACT_DIR, "models_summary.json")
    try:
        with open(summary_path, encoding="utf-8") as summary_file:
            scores = json.load(summary_file)
    except (OSError, ValueError):
        scores = {}
    rows = []
    for filename in model_files:
        try:
            model = joblib.load(os.path.join(ARTIFACT_DIR, filename))
            prediction, confidence, disease_probability = model_probability(model, X)
            name = filename.removesuffix(".joblib")
            rows.append({
                "model": name.replace("_", " ").title(),
                "filename": filename,
                "label": "Disease" if int(prediction) == 1 else "Healthy",
                "prediction": int(prediction), "confidence": confidence,
                "disease_probability": disease_probability,
                "accuracy": float(scores.get(name, {}).get("accuracy") or 0),
            })
        except Exception:
            continue
    return rows


def comparison_html(rows):
    if not rows:
        return '<div class="result-card result-error">No compatible comparison models were available.</div>'
    disease_votes = sum(row["prediction"] == 1 for row in rows)
    consensus = "Disease signal" if disease_votes > len(rows) / 2 else "Healthy signal"
    body = "".join(
        f'''<tr><td>{escape(row['model'])}</td><td>{escape(row['label'])}</td><td>{row['confidence'] * 100:.1f}%</td><td>{row['accuracy'] * 100:.1f}%</td></tr>'''
        for row in sorted(rows, key=lambda item: item["accuracy"], reverse=True)
    )
    return f'''<div class="comparison-panel"><div class="comparison-head"><div><span class="section-label">Model consensus</span><strong>{escape(consensus)}</strong></div><span>{len(rows) - disease_votes} healthy · {disease_votes} disease votes</span></div>
      <div class="history-table-wrap"><table class="history-table"><thead><tr><th>Model</th><th>Prediction</th><th>Confidence</th><th>Validation accuracy</th></tr></thead><tbody>{body}</tbody></table></div></div>'''


def create_explainability_chart(audio_path, rows, selected_filename):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, sr, converted_path = read_audio_samples(audio_path, max_seconds=30)
    fd, chart_path = tempfile.mkstemp(prefix="aerova-explain-", suffix=".png")
    os.close(fd)
    try:
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), facecolor="#071d2d")
        fig.subplots_adjust(hspace=.42, left=.09, right=.96, top=.92, bottom=.10)
        axes[0].specgram(y, NFFT=1024, Fs=sr, noverlap=768, cmap="magma")
        axes[0].set(title="Cough frequency spectrogram", xlabel="Time (seconds)", ylabel="Frequency (Hz)")
        selected = next((row for row in rows if row["filename"] == selected_filename), rows[0])
        values = [1 - selected["disease_probability"], selected["disease_probability"]]
        bars = axes[1].barh(["Healthy", "Disease"], values, color=["#61d8b0", "#ff806f"])
        axes[1].set_xlim(0, 1); axes[1].set_xlabel("Model probability"); axes[1].set_title(f"Confidence explanation · {selected['model']}")
        for bar, value in zip(bars, values):
            axes[1].text(min(value + .02, .92), bar.get_y() + bar.get_height()/2, f"{value*100:.1f}%", va="center", color="white", weight="bold")
        for ax in axes:
            ax.set_facecolor("#102d3c"); ax.tick_params(colors="#d9edf4"); ax.title.set_color("white"); ax.xaxis.label.set_color("#b8d2dc"); ax.yaxis.label.set_color("#b8d2dc")
            for spine in ax.spines.values(): spine.set_color("#416274")
        fig.savefig(chart_path, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return chart_path
    finally:
        if converted_path and os.path.exists(converted_path):
            try:
                os.remove(converted_path)
            except OSError:
                pass


def extract_audio_features(audio_path, n_mfcc=N_MFCC):
    """Extract features without using librosa's slow WebM/audioread fallback."""
    converted_path = None
    try:
        y, sr, converted_path = read_audio_samples(audio_path, max_seconds=30)

        features = {}
        # NumPy STFT avoids librosa/Numba's multi-minute first-call compilation
        # on Python 3.14 while producing the same 50 model input fields.
        frame_length, hop_length = 2048, 512
        if y.size < frame_length:
            y = np.pad(y, (0, frame_length - y.size))
        frame_count = 1 + (y.size - frame_length) // hop_length
        offsets = np.arange(frame_length)[None, :] + hop_length * np.arange(frame_count)[:, None]
        frames = y[offsets]
        windowed = frames * np.hanning(frame_length).astype(np.float32)
        spectrum = np.abs(np.fft.rfft(windowed, axis=1)).T
        power_spectrum = spectrum**2

        def hz_to_mel(hz):
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel):
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        n_mels = 128
        mel_points = np.linspace(hz_to_mel(0.0), hz_to_mel(sr / 2.0), n_mels + 2)
        bins = np.floor((frame_length + 1) * mel_to_hz(mel_points) / sr).astype(int)
        bins = np.clip(bins, 0, spectrum.shape[0] - 1)
        filters = np.zeros((n_mels, spectrum.shape[0]), dtype=np.float32)
        for index in range(n_mels):
            left, center, right = bins[index : index + 3]
            if center > left:
                filters[index, left:center] = np.arange(center - left) / (center - left)
            if right > center:
                filters[index, center:right] = np.arange(right - center, 0, -1) / (right - center)
        mel_power = np.maximum(filters @ power_spectrum, 1e-10)
        mel_db = 10.0 * np.log10(mel_power)
        mfcc = dct(mel_db, type=2, axis=0, norm="ortho")[:n_mfcc]
        mfcc_mean = np.mean(mfcc, axis=1)
        mfcc_var = np.var(mfcc, axis=1)
        features.update({f"mfcc_{i+1}_mean": float(mfcc_mean[i]) for i in range(n_mfcc)})
        features.update({f"mfcc_{i+1}_var": float(mfcc_var[i]) for i in range(n_mfcc)})

        zcr = np.mean(np.abs(np.diff(np.signbit(frames), axis=1)), axis=1)
        features["zero_crossing_rate_mean"] = float(np.mean(zcr))
        features["zero_crossing_rate_var"] = float(np.var(zcr))

        frequencies = np.fft.rfftfreq(frame_length, d=1.0 / sr)[:, None]
        magnitude_sum = np.maximum(np.sum(spectrum, axis=0, keepdims=True), 1e-10)
        centroid = np.sum(frequencies * spectrum, axis=0, keepdims=True) / magnitude_sum
        features["spectral_centroid_mean"] = float(np.mean(centroid))
        features["spectral_centroid_var"] = float(np.var(centroid))

        bandwidth = np.sqrt(
            np.sum(((frequencies - centroid) ** 2) * spectrum, axis=0, keepdims=True)
            / magnitude_sum
        )
        features["spectral_bandwidth_mean"] = float(np.mean(bandwidth))
        features["spectral_bandwidth_var"] = float(np.var(bandwidth))

        cumulative = np.cumsum(spectrum, axis=0)
        thresholds = 0.85 * cumulative[-1]
        rolloff_bins = np.argmax(cumulative >= thresholds[None, :], axis=0)
        rolloff = frequencies[rolloff_bins, 0]
        features["spectral_rolloff_mean"] = float(np.mean(rolloff))
        features["spectral_rolloff_var"] = float(np.var(rolloff))

        chroma = np.zeros((12, spectrum.shape[1]), dtype=np.float32)
        positive_freqs = frequencies[:, 0]
        valid = positive_freqs >= 27.5
        pitch_classes = np.mod(np.rint(12 * np.log2(positive_freqs[valid] / 440.0) + 69), 12).astype(int)
        for pitch_class in range(12):
            chroma[pitch_class] = np.sum(spectrum[valid][pitch_classes == pitch_class], axis=0)
        chroma /= np.maximum(np.sum(chroma, axis=0, keepdims=True), 1e-10)
        features["chroma_mean"] = float(np.mean(chroma))
        features["chroma_var"] = float(np.var(chroma))

        rms = np.sqrt(np.mean(frames**2, axis=1))
        features["rms_mean"] = float(np.mean(rms))
        features["rms_var"] = float(np.var(rms))

        return features
    finally:
        if converted_path and os.path.exists(converted_path):
            try:
                os.remove(converted_path)
            except OSError:
                pass


def build_input_dataframe(audio_path, gender, age, cough_detected, respiratory_condition, fever_muscle_pain, preprocessor):
    audio_features = extract_audio_features(audio_path)
    row = {
        "gender": str(gender).strip().lower(),
        "age": float(age),
        "cough_detected": float(cough_detected),
        "respiratory_condition": parse_bool(respiratory_condition),
        "fever_muscle_pain": parse_bool(fever_muscle_pain),
    }
    row.update(audio_features)
    expected_columns = list(getattr(preprocessor, "feature_names_in_", row.keys()))
    categorical_columns = set(preprocessor.transformers_[1][2])
    for column in expected_columns:
        if column not in row:
            row[column] = "unknown" if column in categorical_columns else 0.0
    df = pd.DataFrame([row], columns=expected_columns)
    return df


def _download_to_temp(url):
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()
        tmpfd, tmpname = tempfile.mkstemp(suffix=os.path.splitext(url)[-1] or ".wav")
        with os.fdopen(tmpfd, "wb") as f:
            for chunk in r.iter_content(1024 * 8):
                if chunk:
                    f.write(chunk)
        return tmpname
    except Exception as exc:
        raise RuntimeError(f"Failed to download audio from URL: {exc}")


def resolve_audio_path(audio_data, audio_file, audio_url):
    if audio_url:
        return _download_to_temp(audio_url)

    if audio_file is not None:
        if isinstance(audio_file, dict):
            for key in ["path", "name", "file_name", "filepath", "tmp_path"]:
                if key in audio_file and audio_file[key]:
                    return audio_file[key]
        for attribute in ("path", "name", "file_name", "filepath", "tmp_path"):
            value = getattr(audio_file, attribute, None)
            if value:
                return value
        if isinstance(audio_file, str):
            return audio_file

    if audio_data is not None:
        if isinstance(audio_data, dict):
            for key in ["path", "name", "file_name", "filepath", "tmp_path"]:
                if key in audio_data and audio_data[key]:
                    return audio_data[key]
        for attribute in ("path", "name", "file_name", "filepath", "tmp_path"):
            value = getattr(audio_data, attribute, None)
            if value:
                return value
        return audio_data

    return None


def predict(audio_data, audio_file, audio_url, manual_notes, model_filename, gender, age, cough_detected, respiratory_condition, fever_muscle_pain):
    try:
        preprocessor = load_preprocessor()

        audio_path = resolve_audio_path(audio_data, audio_file, audio_url)
        if audio_path is None:
            return '<div class="result-card result-error"><strong>No audio yet</strong><span>Upload a recording, use your microphone, or paste an audio URL to begin.</span></div>', "", "", None, "", {}

        audio_quality = validate_audio_quality(audio_path)
        audio_quality_html = quality_html(audio_quality)
        if audio_quality["blocking"]:
            return (
                '<div class="result-card result-error"><strong>Recording needs attention</strong><span>The signal is too short or quiet for a reliable readout. Please record again.</span></div>',
                "", audio_quality_html, None, "", {"quality": audio_quality},
            )

        input_df = build_input_dataframe(
            audio_path,
            gender,
            age,
            cough_detected,
            respiratory_condition,
            fever_muscle_pain,
            preprocessor,
        )

        X = preprocessor.transform(input_df)

        model_path = os.path.join(ARTIFACT_DIR, model_filename) if model_filename else ""
        if not model_path or not os.path.exists(model_path):
            compatible_files = compatible_model_files(preprocessor, list_available_models())
            fallback = choose_best_model(compatible_files)
            model_path = os.path.join(ARTIFACT_DIR, fallback) if fallback else ""
        if not model_path or not os.path.exists(model_path):
            return f'<div class="result-card result-error"><strong>Model unavailable</strong><span>{escape(str(model_filename or "No compatible model found"))}</span></div>', "", audio_quality_html, None, "", {"quality": audio_quality}

        model = joblib.load(model_path)
        expected_features = len(preprocessor.get_feature_names_out())
        actual_features = getattr(model, "n_features_in_", expected_features)
        if actual_features != expected_features:
            fallback = choose_best_model(compatible_model_files(preprocessor, list_available_models()))
            if not fallback:
                raise ValueError(f"Model '{os.path.basename(model_path)}' is incompatible with the loaded preprocessor.")
            model_path = os.path.join(ARTIFACT_DIR, fallback)
            model = joblib.load(model_path)
        # Some saved ensemble models retain n_jobs=-1. On restricted Windows
        # hosts that makes joblib create worker pipes and raises WinError 5.
        if hasattr(model, "n_jobs"):
            model.n_jobs = 1
        prediction, confidence, covid_proba = model_probability(model, X)
        healthy_proba = 1.0 - covid_proba

        detail_result = build_prediction_result(
            prediction=prediction,
            probability=confidence,
            notes=str(manual_notes or ""),
            respiratory_condition=parse_bool(respiratory_condition),
            fever_muscle_pain=parse_bool(fever_muscle_pain),
        )
        label = "Urgent review" if detail_result["status"] == "urgent" else ("Disease" if prediction == 1 else "Healthy")

        risk = str(detail_result["risk_level"]).lower()
        status_class = "status-healthy" if label == "Healthy" else "status-review"
        risk_class = f"risk-{risk}"
        symptoms = detail_result["symptoms_detected"] or ["No symptoms reported"]
        symptom_chips = "".join(f'<span class="symptom-chip">{escape(str(item))}</span>' for item in symptoms)
        result_html = f'''<div class="result-card {status_class}">
            <div class="result-kicker">SCREENING SIGNAL</div>
            <div class="result-heading"><span>{escape(label)}</span><span class="confidence">{confidence * 100:.1f}% confidence</span></div>
            <p class="result-summary">{escape(detail_result["final_classification"])}</p>
            <div class="meter"><span style="width: {confidence * 100:.1f}%"></span></div>
            <div class="result-meta"><span class="risk-pill {risk_class}">{escape(risk)} risk</span><span>Model: {escape(os.path.basename(model_path))}</span></div>
        </div>'''
        details_html = f'''<div class="details-panel">
            <div class="detail-section"><div class="section-label">What we heard</div><p>{escape(detail_result["sound_classification"])}</p></div>
            <div class="detail-section"><div class="section-label">Context signals</div><p>{escape(detail_result["symptom_classification"])}</p><div class="chips">{symptom_chips}</div></div>
            <div class="recommendation"><div class="section-label">Next best step</div><p>{escape(detail_result["recommendation"])}</p></div>
        </div>'''
        model_files = compatible_model_files(preprocessor, list_available_models())
        comparison_rows = compare_models(X, model_files)
        chart_path = create_explainability_chart(audio_path, comparison_rows, os.path.basename(model_path))
        metadata = {
            "quality": audio_quality, "comparison": comparison_rows,
            "confidence": confidence, "label": label, "risk": risk,
            "model": os.path.basename(model_path), "chart_path": chart_path,
        }
        return result_html, details_html, audio_quality_html, chart_path, comparison_html(comparison_rows), metadata
    except Exception as exc:
        return f'<div class="result-card result-error"><strong>Something went wrong</strong><span>{escape(str(exc))}</span></div>', "", "", None, "", {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", os.environ.get("GRADIO_PORT", "7860"))),
        help="Server port for Gradio",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get(
            "GRADIO_HOST", os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
        ),
        help="Server host for Gradio",
    )
    parser.add_argument("--share", action="store_true", help="Enable Gradio public share link")
    args = parser.parse_args()

    model_files = list_available_models()
    try:
        model_files = compatible_model_files(load_preprocessor(), model_files)
    except Exception:
        model_files = []
    default_model = choose_best_model(model_files)

    iface = build_app(predict, model_files, default_model)

    def find_free_port(start_port: int, end_port: int = 7999):
        import socket

        for p in range(start_port, end_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind((args.host, p))
                    return p
                except OSError:
                    continue
        raise RuntimeError(f"No free ports in range {start_port}-{end_port}")

    launch_options = {
        "server_name": args.host,
        "server_port": args.port,
        "share": args.share,
        "show_error": True,
        "theme": gr.themes.Base(),
        "css": APP_CSS,
    }
    try:
        iface.launch(**launch_options)
    except OSError as exc:
        try:
            free_port = find_free_port(args.port + 1, args.port + 200)
            print(f"Port {args.port} unavailable, retrying on free port {free_port}...")
            launch_options["server_port"] = free_port
            iface.launch(**launch_options)
        except Exception:
            raise


if __name__ == "__main__":
    main()
