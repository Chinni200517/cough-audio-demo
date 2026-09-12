import os
import joblib
import pandas as pd
import numpy as np
import librosa
import tempfile
import subprocess
from pathlib import Path
from imageio_ffmpeg import get_ffmpeg_exe

ARTIFACT_DIR = Path('output')
PREPROCESSOR_PATH = ARTIFACT_DIR / 'preprocessor.joblib'

if not PREPROCESSOR_PATH.exists():
    raise SystemExit('Missing preprocessor.joblib in output/')

preprocessor = joblib.load(PREPROCESSOR_PATH)


def convert_audio_to_wav(input_path):
    tmpfd, output_path = tempfile.mkstemp(suffix='.wav')
    os.close(tmpfd)
    ffmpeg_bin = get_ffmpeg_exe()
    cmd = [str(ffmpeg_bin), '-y', '-i', str(input_path), '-acodec', 'pcm_s16le', '-ar', '22050', str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'ffmpeg failed: {result.stderr}')
    if Path(output_path).exists():
        return Path(output_path)
    raise RuntimeError('ffmpeg did not produce a wav file')


def extract_audio_features(audio_path):
    try:
        y, sr = librosa.load(str(audio_path), sr=None)
    except Exception:
        audio_path = convert_audio_to_wav(audio_path)
        y, sr = librosa.load(str(audio_path), sr=None)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    features = {f'mfcc_{i+1}_mean': float(np.mean(mfcc, axis=1)[i]) for i in range(20)}
    features.update({f'mfcc_{i+1}_var': float(np.var(mfcc, axis=1)[i]) for i in range(20)})
    features['zero_crossing_rate_mean'] = float(np.mean(librosa.feature.zero_crossing_rate(y)))
    features['zero_crossing_rate_var'] = float(np.var(librosa.feature.zero_crossing_rate(y)))
    features['spectral_centroid_mean'] = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    features['spectral_centroid_var'] = float(np.var(librosa.feature.spectral_centroid(y=y, sr=sr)))
    features['spectral_bandwidth_mean'] = float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
    features['spectral_bandwidth_var'] = float(np.var(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
    features['spectral_rolloff_mean'] = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
    features['spectral_rolloff_var'] = float(np.var(librosa.feature.spectral_rolloff(y=y, sr=sr)))
    features['chroma_mean'] = float(np.mean(librosa.feature.chroma_stft(y=y, sr=sr)))
    features['chroma_var'] = float(np.var(librosa.feature.chroma_stft(y=y, sr=sr)))
    features['rms_mean'] = float(np.mean(librosa.feature.rms(y=y)))
    features['rms_var'] = float(np.var(librosa.feature.rms(y=y)))
    return features

file_path = Path('public_dataset/00ccf4e3-6e4f-4e6b-a16d-11b4a8999d1e.webm')
if not file_path.exists():
    raise SystemExit(f'Missing file: {file_path}')

row = {
    'gender': 'unknown',
    'age': 30.0,
    'cough_detected': 0.5,
    'respiratory_condition': False,
    'fever_muscle_pain': False,
}
row.update(extract_audio_features(file_path))
df = pd.DataFrame([row])
X = preprocessor.transform(df)
model_files = [f for f in ARTIFACT_DIR.iterdir() if f.suffix == '.joblib' and f.name != 'preprocessor.joblib']
if not model_files:
    raise SystemExit('No model file found in output/')
model_path = model_files[0]
model = joblib.load(model_path)
pred = model.predict(X)[0]
print('model:', model_path.name)
print('prediction:', pred, '=>', 'Disease' if pred == 1 else 'Healthy')
