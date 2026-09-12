from html import escape
from datetime import datetime
import os
import logging
import time
from functools import lru_cache
import re
import secrets
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import gradio as gr
import requests

from reporting import create_pdf_report, history_dashboard_html, save_assessment, send_prescription_email

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
USERS_PATH = RUNTIME_DIR / "users.json"

# Global active key store (allows setting via UI, environment, or .env)
ACTIVE_GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY", "").strip()
    or os.environ.get("GOOGLE_API_KEY", "").strip()
)

APP_CSS = """
:root {
  --bg: #071b24;
  --bg-strong: #0b3440;
  --panel: rgba(10, 35, 43, 0.94);
  --panel-soft: rgba(15, 58, 63, 0.9);
  --ink: #f4fbf8;
  --muted: #bfd5d2;
  --primary: #20b7a5;
  --primary-deep: #087f78;
  --secondary: #a9f0d5;
  --accent: #f17c55;
  --success: #1a9b68;
  --warning: #bd7810;
  --line: rgba(170, 228, 215, 0.3);
  --shadow: 0 22px 50px rgba(5, 17, 29, 0.45);
}

body, .gradio-container {
  background: radial-gradient(circle at top left, #15505a 0%, #092c35 38%, #06171e 100%) !important;
  color: var(--ink) !important;
  font-family: 'Segoe UI', Arial, sans-serif !important;
}

.gradio-container {
  max-width: 1280px !important;
  margin: auto;
  padding: 24px 18px 40px !important;
}

.gradio-container .block {
  border-radius: 22px !important;
}

.hero {
  padding: 28px 30px 20px;
  border: 1px solid var(--line);
  background: linear-gradient(135deg, rgba(18,58,80,0.94) 0%, rgba(11,89,109,0.92) 45%, rgba(23,128,150,0.9) 100%);
  border-radius: 24px;
  color: white;
  box-shadow: var(--shadow);
}

.hero-hospital {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 170px;
}

.hero-left {
  max-width: 68%;
}

.hero-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-end;
}

.eyebrow, .section-label, .result-kicker {
  color: #bfeaf2;
  font: 700 11px/1.2 Arial, sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.hero h1 {
  margin: 12px 0 8px;
  font-size: clamp(28px, 4vw, 52px);
  line-height: 1.02;
  font-weight: 700;
  letter-spacing: -0.04em;
}

.hero p {
  max-width: 640px;
  color: rgba(255, 255, 255, 0.82);
  font: 16px/1.6 Arial, sans-serif;
  margin: 0;
}

.brand-banner {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  padding: 8px 14px;
  backdrop-filter: blur(6px);
}

.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #9fe9ff, #69c6d2);
  color: #073d4b;
  font-weight: 800;
  box-shadow: inset 0 2px 10px rgba(255,255,255,.4);
}

.status-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.portal-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(7, 19, 28, 0.38);
  border: 1px solid rgba(148, 196, 220, 0.22);
  color: white;
  border-radius: 999px;
  padding: 8px 12px;
  font: 700 11px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.portal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #9ae9d1;
  box-shadow: 0 0 10px rgba(154, 233, 209, 0.9);
}

.panel {
  background: rgba(12, 27, 38, 0.88);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(2px);
  margin-top: 14px;
}

.panel-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 4px;
  color: var(--ink);
}

.panel-copy {
  color: var(--muted);
  font: 13px/1.5 Arial, sans-serif;
  margin: 0 0 16px;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 22px;
}

.metric-item {
  background: rgba(148, 196, 220, 0.08);
  border: 1px solid rgba(148, 196, 220, 0.18);
  border-radius: 16px;
  padding: 14px 12px;
}

.metric-label {
  display: block;
  font: 700 10px Arial, sans-serif;
  color: var(--muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 8px;
  font: 700 24px/1 Arial, sans-serif;
  color: var(--ink);
}

.metric-trend {
  display: inline-block;
  margin-top: 8px;
  font: 700 11px Arial, sans-serif;
  color: var(--success);
}

.audio-box {
  border: 1px dashed #8ec6d4;
  background: linear-gradient(180deg, #f1fbff 0%, #edf8f7 100%);
  border-radius: 16px;
  padding: 6px;
}

label span, .gr-input-label {
  color: var(--ink) !important;
  font-family: Arial, sans-serif !important;
  font-weight: 700 !important;
}

input, textarea, select {
  font-family: Arial, sans-serif !important;
  border-color: #d5e4ee !important;
  border-radius: 12px !important;
  box-shadow: none !important;
  color: #ffffff !important;
  background-color: rgba(14, 27, 40, 0.95) !important;
}

input:focus, textarea:focus, select:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(13,106,138,.12) !important;
}

.primary-button {
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-deep) 100%) !important;
  color: white !important;
  border: 0 !important;
  border-radius: 12px !important;
  font: 700 15px Arial, sans-serif !important;
  box-shadow: 0 14px 30px rgba(13,106,138,.20) !important;
  cursor: pointer;
}

.primary-button:hover {
  filter: brightness(1.05);
}

.secondary-button {
  border: 1px solid #cfe0eb !important;
  color: #0c2e38 !important;
  border-radius: 12px !important;
  background: #f4fbff !important;
  font-weight: 700 !important;
  cursor: pointer;
}

.demo-fast-btn {
  background: linear-gradient(135deg, #00e5b0 0%, #059669 100%) !important;
  color: #041620 !important;
  font-weight: 800 !important;
  font-size: 15px !important;
  border-radius: 14px !important;
  padding: 14px 20px !important;
  box-shadow: 0 10px 25px rgba(0, 229, 176, 0.35) !important;
  border: none !important;
  cursor: pointer;
  width: 100%;
}

.progress {
  display: flex;
  gap: 12px;
  margin: 18px 0 20px;
}

.progress-item {
  flex: 1;
  border-top: 4px solid rgba(255, 255, 255, 0.15);
  padding-top: 10px;
  color: var(--muted);
  font: 800 11px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  transition: all 0.2s ease;
}

.progress-item.active {
  color: var(--secondary);
  border-color: var(--secondary);
}

.login-panel {
  max-width: 580px;
  margin: 40px auto;
  padding: 36px 32px;
  background: rgba(12, 27, 38, 0.92);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow);
}

.login-mark {
  display: inline-block;
  font: 800 24px/1 Arial, sans-serif;
  color: white;
  letter-spacing: 0.08em;
}

.login-copy {
  color: var(--muted);
  font: 14px/1.5 Arial, sans-serif;
  margin: 0 0 20px;
}

.captcha-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.captcha-question {
  color: var(--secondary);
  font: 800 15px Arial, sans-serif;
  padding: 12px 16px;
  background: rgba(169, 240, 213, 0.12);
  border: 1px solid rgba(169, 240, 213, 0.3);
  border-radius: 12px;
}

.notice {
  color: #ff8e8e;
  font: 600 13px Arial, sans-serif;
  padding: 10px 0;
}

.notification {
  color: var(--secondary);
  font: 600 13px Arial, sans-serif;
  margin-top: 10px;
}

.share-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.share-action {
  background: #f4fbff;
  border: 1px solid #d3e2ec;
  border-radius: 10px;
  padding: 8px 14px;
  font: 700 12px Arial, sans-serif;
  color: var(--primary-deep) !important;
  text-decoration: none !important;
}

.share-action:hover {
  background: #e7f4fb;
}

.share-action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 13px;
  text-decoration: none !important;
  transition: all 0.2s ease;
}

.link-wa {
  background: #25d366;
  color: #ffffff !important;
}

.link-wa:hover {
  background: #1eb956;
}

.link-email {
  background: #38bdf8;
  color: #041620 !important;
}

.link-download {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff !important;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.share-center-wrap {
  background: rgba(10, 28, 40, 0.95);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 20px;
  padding: 22px 24px;
  margin: 20px 0;
  box-shadow: 0 14px 35px rgba(0, 0, 0, 0.4);
}

.share-center-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
}

.share-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 14px;
}

@media (max-width: 768px) {
  .share-grid {
    grid-template-columns: 1fr;
  }
  .hero-hospital {
    flex-direction: column;
    align-items: flex-start;
  }
  .hero-left, .hero-right {
    max-width: 100%;
    width: 100%;
  }
  .hero-right {
    align-items: flex-start;
  }
  .dashboard-metrics {
    grid-template-columns: 1fr;
  }
}
"""

# ---------------------------------------------------------------------------
# AUTHENTICATION & USER STORE
# ---------------------------------------------------------------------------
def _load_users() -> dict:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not USERS_PATH.exists():
        default_users = {
            "clinician@hospital-aerova.org": {
                "name": "Dr. Clinician",
                "password_hash": _hash_password("Doctor@2026!"),
                "created_at": datetime.now().isoformat(),
            }
        }
        USERS_PATH.write_text(json.dumps(default_users, indent=2), encoding="utf-8")
        return default_users
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}:{hashed.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hashed = stored_hash.split(":", 1)
        test_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
        return secrets.compare_digest(hashed, test_hash)
    except Exception:
        return False


def _validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter (A-Z)."
    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter (a-z)."
    if not re.search(r"\d", password):
        return False, "Password must include at least one number (0-9)."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must include at least one special character (!@#$%^&*)."
    return True, "Strong password verified."


def _handle_signup(name, email, password, confirm_password):
    name_text = str(name or "").strip()
    email_text = str(email or "").strip().lower()
    pass_text = str(password or "")
    confirm_text = str(confirm_password or "")

    if not name_text:
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Please enter your full name or clinician title.</div>'
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_text):
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Please enter a valid email address (e.g., doctor@hospital-aerova.org).</div>'
    if pass_text != confirm_text:
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Passwords do not match. Please re-enter both carefully.</div>'

    is_strong, msg = _validate_password_strength(pass_text)
    if not is_strong:
        return gr.update(visible=True), gr.update(visible=False), "", f'<div class="notice">⚠️ {msg}</div>'

    users = _load_users()
    if email_text in users:
        if _verify_password(pass_text, users[email_text]["password_hash"]):
            return gr.update(visible=False), gr.update(visible=True), email_text, f'<div class="notification">✅ Welcome back, {escape(name_text)}! Signed in to Team NOVIX.</div>'
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ An account with this email already exists. Please sign in instead.</div>'

    users[email_text] = {
        "name": name_text,
        "password_hash": _hash_password(pass_text),
        "created_at": datetime.now().isoformat(),
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temp = USERS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(users, indent=2), encoding="utf-8")
    os.replace(temp, USERS_PATH)

    welcome_msg = f'<div class="notification">🎉 Welcome, {escape(name_text)}! Your Team NOVIX account is created and ready for triage.</div>'
    return gr.update(visible=False), gr.update(visible=True), email_text, welcome_msg


def _demo_login(email, password, captcha_entry, captcha_answer):
    email_text = str(email or "").strip().lower()
    password_text = str(password or "")

    if str(captcha_entry or "").strip() != str(captcha_answer or ""):
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ CAPTCHA answer is incorrect. Please refresh and try again.</div>'

    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_text):
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Please enter a valid email address.</div>'

    users = _load_users()
    if email_text in users:
        if _verify_password(password_text, users[email_text]["password_hash"]):
            name = users[email_text].get("name", email_text)
            return gr.update(visible=False), gr.update(visible=True), email_text, f'<div class="notification">✅ Welcome back, {escape(name)}! Signed in securely to Team NOVIX.</div>'
        else:
            return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Incorrect password for this account.</div>'

    is_strong, msg = _validate_password_strength(password_text)
    if is_strong:
        users[email_text] = {
            "name": email_text.split("@")[0].title(),
            "password_hash": _hash_password(password_text),
            "created_at": datetime.now().isoformat(),
        }
        USERS_PATH.write_text(json.dumps(users, indent=2), encoding="utf-8")
        return gr.update(visible=False), gr.update(visible=True), email_text, f'<div class="notification">✅ Signed in. Reports will be addressed to {escape(email_text)}.</div>'

    return gr.update(visible=True), gr.update(visible=False), "", f'<div class="notice">⚠️ {msg}</div>'


def _fast_demo_login():
    demo_email = "clinician@hospital-aerova.org"
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        demo_email,
        '<div class="notification">⚡ Instant Demo Access granted for Team NOVIX. Ready to screen cough audio!</div>',
    )


def _new_captcha():
    first = secrets.randbelow(8) + 2
    second = secrets.randbelow(8) + 2
    return f"What is {first} + {second}?", str(first + second)


# ---------------------------------------------------------------------------
# GEMINI & AEROVA ASSISTANT
# ---------------------------------------------------------------------------
GEMINI_LOG = logging.getLogger("aerova.gemini")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GEMINI_SYSTEM_INSTRUCTION = (
    "You are AEROVA-BOT, a helpful, objective clinical respiratory screening assistant created by Chinni200517 "
    "for Team NOVIX. You help patients and healthcare providers understand cough audio triage signals, acoustic biomarkers, "
    "MFCC sound characteristics, model confidence, and risk assessment levels. Always clarify that AEROVA is a screening aid, "
    "not a replacement for clinician diagnosis or hospital emergency triage. Keep responses clear, concise, and professional."
)


def _message_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text", ""))
    if isinstance(content, (list, tuple)):
        return " ".join(_message_text(item) for item in content)
    return str(content or "")


def _gemini_history(history):
    payload = []
    for item in history or []:
        role = item.get("role", "")
        text = _message_text(item.get("content", ""))
        if not text:
            continue
        gemini_role = "user" if role == "user" else "model"
        payload.append({"role": gemini_role, "parts": [{"text": text}]})
    return payload[-12:]


@lru_cache(maxsize=8)
def _gemini_fallback_models(api_key, cache_period):
    """Discover text Flash models; cache for a five-minute period per key."""
    models = []
    page_token = None
    for _ in range(3):
        params = {"pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
        try:
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": api_key}, params=params, timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            for item in data.get("models", []):
                name = item.get("name", "").removeprefix("models/")
                if (
                    re.fullmatch(r"gemini-\d+(?:\.\d+)?-flash(?:-lite)?", name)
                    and "generateContent" in item.get("supportedGenerationMethods", [])
                ):
                    models.append(name)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        except Exception:
            break
    return tuple(sorted(set(models), key=lambda name: (
        not name.endswith("-lite"),
        tuple(-int(n) for n in re.search(r"\d+(?:\.\d+)?", name)[0].split(".")),
    )))


def _gemini_request(api_key, model, payload):
    candidates = [model]
    for index, candidate in enumerate(candidates):
        generation_config = {"temperature": 0.3, "maxOutputTokens": 2048}
        if candidate in {"gemini-2.5-flash", "gemini-2.5-flash-lite"}:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        response = requests.post(
            GEMINI_API_URL.format(model=candidate),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json={**payload, "generationConfig": generation_config}, timeout=25,
        )
        try:
            response.raise_for_status()
            return response
        except requests.HTTPError:
            if response.status_code != 404:
                raise
            if index == 0:
                available = _gemini_fallback_models(api_key, int(time.monotonic() // 300))
                candidates.extend([name for name in available if name != model][:2])
            if index == len(candidates) - 1:
                raise
            GEMINI_LOG.warning("Configured Gemini model unavailable; trying %s.", candidates[index + 1])


def _gemini_answer(question, history, api_key=None):
    """Return a Gemini answer when configured, without exposing API failures to users."""
    global ACTIVE_GEMINI_KEY
    key = str(api_key or ACTIVE_GEMINI_KEY or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key:
        key = next(
            (
                str(value).strip()
                for name, value in os.environ.items()
                if name.casefold() == "gemini_api_key"
            ),
            "",
        )
    if not key:
        key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        GEMINI_LOG.warning("Gemini unavailable: set GEMINI_API_KEY in Render Environment or enter in Robot drawer.")
        return None

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite"
    model = model.removeprefix("models/")
    if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", model):
        GEMINI_LOG.warning("Gemini unavailable: GEMINI_MODEL must be a model ID, not a URL.")
        return None
    payload = {
        "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_INSTRUCTION}]},
        "contents": _gemini_history(history) + [
            {"role": "user", "parts": [{"text": question}]}
        ],
    }
    try:
        response = _gemini_request(key, model, payload)
        parts = response.json()["candidates"][0]["content"]["parts"]
        answer = "\n".join(
            part["text"] for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            and not part.get("thought")
        ).strip()
        if not answer:
            GEMINI_LOG.warning("Gemini returned no answer text; check model output limits or safety filtering.")
        return answer or None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        hint = {
            400: "check the API key and request configuration",
            401: "check the API key",
            403: "check API key permissions and restrictions",
            404: "check GEMINI_MODEL availability for this key",
            429: "check Gemini quota and rate limits",
        }.get(status, "the Gemini service could not complete the request")
        GEMINI_LOG.warning("Gemini HTTP %s: %s.", status, hint)
        return None
    except requests.RequestException:
        GEMINI_LOG.warning("Gemini connection failed or timed out; retry and check outbound connectivity.")
        return None
    except (KeyError, IndexError, TypeError, ValueError):
        GEMINI_LOG.warning("Gemini returned no usable candidate; check safety filtering or output limits.")
        return None


def _safe_gemini_answer(question, history, api_key=None):
    try:
        return _gemini_answer(question, history, api_key)
    except Exception:
        return None


def _local_project_answer(lowered):
    if "format" in lowered or "wav" in lowered or "audio" in lowered or "mp3" in lowered:
        return "You can upload WAV, MP3, WEBM, or OGG audio files, or record directly using your microphone."
    if "how does aerova work" in lowered or "work" in lowered:
        return "Sign in to the AEROVA portal, provide a 2–6 second cough audio sample, enter optional clinical symptoms, and generate a machine-learning triage readout."
    if "diagnosis" in lowered or "diagnose" in lowered or "is this a diagnosis" in lowered:
        return "AEROVA cannot diagnose medical conditions. It is an acoustic triage screening aid designed to assist clinical decision-making."
    if "confidence" in lowered or "score" in lowered:
        return "The confidence score reflects acoustic model conviction based on MFCC spectrogram features, not the probability of clinical outcome."
    if "who made" in lowered or "author" in lowered or "team" in lowered or "developer" in lowered:
        return "AEROVA was developed by Chinni200517 for Team NOVIX as an acoustic respiratory clinical triage system."
    return None


def _chat_response(message, history, api_key=None):
    history = list(history or []) if isinstance(history, (list, tuple)) else []
    question = str(message or "").strip()
    if not question:
        return history, ""

    lowered = question.lower()
    local_answer = _local_project_answer(lowered)

    if any(term in lowered for term in ("emergency", "can't breathe", "cannot breathe", "blue lips", "chest pain")):
        answer = "⚠️ EMERGENCY NOTICE: For severe breathing difficulty, blue lips, confusion, or severe chest pain, seek immediate emergency medical care."
    elif local_answer:
        answer = local_answer
    elif (gemini_response := _safe_gemini_answer(question, history, api_key)):
        answer = gemini_response
    else:
        answer = "AEROVA by Team NOVIX analyses acoustic cough patterns using 10 ensemble machine learning models to detect respiratory infection signals. It is a screening aid, not emergency care."

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    return history, ""


# ---------------------------------------------------------------------------
# WORKFLOW UTILITIES & SHARING
# ---------------------------------------------------------------------------
def _continue_audio(audio_data, audio_file, audio_url):
    if audio_data is not None or audio_file is not None or str(audio_url or "").strip():
        return gr.update(visible=False), gr.update(visible=True), ""
    return gr.update(visible=True), gr.update(visible=False), '<div class="notice">⚠️ Please add a cough recording or audio sample before moving to the next step.</div>'


def _build_whatsapp_message(patient_id, label, confidence, risk, model, date, age, gender, summary_text):
    clean_summary = re.sub(r"<[^>]+>", " ", str(summary_text or ""))
    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()
    status_icon = "🟢" if label == "Healthy" else "🔴"
    return (
        f"🏥 *TEAM NOVIX AEROVA - DIGITAL CLINICAL PRESCRIPTION (Rx)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 *Patient ID:* {patient_id}\n"
        f"📅 *Prescription Date:* {date}\n"
        f"👤 *Patient Profile:* {age} yrs · {str(gender).title()}\n"
        f"🤖 *Acoustic Model:* {model}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_icon} *PRIMARY READOUT:* *{str(label)}*\n"
        f"📊 *Confidence:* {float(confidence)*100:.1f}%\n"
        f"⚠️ *Risk Assessment:* {str(risk).upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🩺 *Clinical Directive:* {clean_summary[:400]}...\n\n"
        f"📄 *Verified PDF Medical Report is attached with QR Code.*\n"
        f"_Notice: Acoustic screening triage aid. Consult a clinician for emergency care._"
    )


def _generate_whatsapp_link(phone, wa_message_text):
    phone_clean = re.sub(r"[^\d]", "", str(phone or "").strip())
    if not wa_message_text:
        return '<div style="color: #ff8e8e; font-size: 12px;">⚠️ Please run assessment to generate clinical report first.</div>'
    encoded_msg = quote(str(wa_message_text))
    if phone_clean:
        wa_url = f"https://wa.me/{phone_clean}?text={encoded_msg}"
        target_desc = f"+{phone_clean}"
    else:
        wa_url = f"https://wa.me/?text={encoded_msg}"
        target_desc = "your selected contact / patient"

    return f'''
    <div style="margin-top: 10px; background: rgba(37, 211, 102, 0.12); border: 1px solid #25d366; border-radius: 12px; padding: 14px 18px;">
      <div style="color: #25d366; font-weight: 800; font-size: 13px; margin-bottom: 6px;">💬 WhatsApp Share Link Ready:</div>
      <a href="{escape(wa_url)}" target="_blank" class="share-action-link link-wa" style="font-size: 14px; font-weight: 800; padding: 12px 22px;">
        🚀 Click to Open WhatsApp & Send to {escape(target_desc)}
      </a>
      <div style="color: var(--muted); font-size: 11px; margin-top: 8px;">Tip: Once WhatsApp opens, tap <b>Attach 📎 → Document</b> to attach your downloaded PDF report!</div>
    </div>
    '''


def _handle_send_email_now(recipient, sender, pwd, patient_id, html_report, pdf_path):
    recipient_clean = str(recipient or "").strip()
    if not recipient_clean or "@" not in recipient_clean:
        return '<div class="notice">⚠️ Please enter a valid recipient email address.</div>'
    if not html_report:
        return '<div class="notice">⚠️ Please run an acoustic assessment first to generate the prescription.</div>'

    subject = f"TEAM NOVIX Medical Prescription (Rx) - {patient_id or 'AEROVA'}"
    success, msg = send_prescription_email(
        to_email=recipient_clean,
        subject=subject,
        html_content=html_report,
        pdf_path=pdf_path if pdf_path and os.path.exists(pdf_path) else None,
        sender_email=sender,
        sender_password=pwd,
    )
    if success:
        return f'<div class="notification">✅ {escape(msg)}</div>'
    return f'<div class="notice">⚠️ Automated Delivery Notice: {escape(msg)}</div>'


def _handle_open_gmail_compose(recipient, patient_id, wa_message_text):
    encoded_to = quote(str(recipient or "").strip())
    subject = f"TEAM NOVIX Medical Prescription (Rx) - {patient_id or 'AEROVA'}"
    encoded_sub = quote(subject)
    encoded_body = quote(str(wa_message_text or ""))
    gmail_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={encoded_to}&su={encoded_sub}&body={encoded_body}"
    return (
        f'<div style="margin-top: 10px; background: rgba(56, 189, 248, 0.12); border: 1px solid #38bdf8; border-radius: 12px; padding: 14px 18px;">'
        f'<div style="color: #38bdf8; font-weight: 800; font-size: 13px; margin-bottom: 6px;">✉️ Gmail Web Compose Ready:</div>'
        f'<a href="{escape(gmail_url)}" target="_blank" class="share-action-link link-email" style="font-size: 14px; font-weight: 800; padding: 12px 22px; background: linear-gradient(135deg, #ea4335, #c5221f); color: #fff;">'
        f'🚀 Click to Open in Gmail Compose</a>'
        f'<div style="color: var(--muted); font-size: 11px; margin-top: 6px;">Opens Gmail in a new tab with recipient, subject, and prescription pre-filled.</div>'
        f'</div>'
    )


def _run_prediction(predict_fn, email, *values):
    payload = predict_fn(*values)
    result, details = payload[:2]
    extended = len(payload) >= 6
    quality_markup = payload[2] if extended else ""
    chart_path = payload[3] if extended else None
    comparison_markup = payload[4] if extended else ""
    metadata = payload[5] if extended else {}
    patient_id = f"AUR-{datetime.now():%Y%m%d}-{secrets.token_hex(3).upper()}"
    report_date = datetime.now().strftime("%d %B %Y, %I:%M %p")
    gender = values[5] if len(values) > 5 else "unknown"
    age = values[6] if len(values) > 6 else "Not provided"
    model = values[4] if len(values) > 4 else "AEROVA Extra Trees Classifier"

    label = str(metadata.get("label", "Readout"))
    confidence = float(metadata.get("confidence", 0.85))
    risk = str(metadata.get("risk", "Low risk"))

    verdict_color = "#00e5b0" if label == "Healthy" else "#f43f5e"
    verdict_icon = "🟢" if label == "Healthy" else "🔴"

    report_text = f"TEAM NOVIX AEROVA Medical Prescription | Patient ID: {patient_id}\n" + re.sub(r"<[^>]+>", " ", result + " " + details)
    report_text = re.sub(r"\s+", " ", report_text).strip()[:1800]
    subject = f"TEAM NOVIX Medical Prescription (Rx) - {patient_id}"
    email_link = f"mailto:{quote(str(email or ''))}?subject={quote(subject)}&body={quote(report_text)}"

    wa_message = _build_whatsapp_message(
        patient_id=patient_id, label=label, confidence=confidence, risk=risk,
        model=model, date=report_date, age=age, gender=gender, summary_text=details,
    )
    wa_default_link = f"https://wa.me/?text={quote(wa_message)}"

    email_report = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;background:#050d17;font-family:'Segoe UI',Arial,sans-serif;color:#f1f5f9;padding:20px;">
  <div style="max-width:780px;margin:0 auto;background:#0e1728;border:2px solid #1e3a5f;border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.6);">
    <div style="background:linear-gradient(135deg,#0c233c,#006d77);padding:30px 36px;border-bottom:3px solid #00e5b0;">
      <table role="presentation" style="width:100%;border-collapse:collapse;">
        <tr>
          <td>
            <div style="font-size:12px;letter-spacing:2.5px;font-weight:800;text-transform:uppercase;color:#7bf5d4;">TEAM NOVIX · CLINICAL PULMONOLOGY</div>
            <h1 style="margin:8px 0 4px;font-size:32px;font-weight:900;color:#ffffff;">AEROVA DIGITAL CLINICAL PRESCRIPTION</h1>
            <div style="font-size:13px;color:#d8f3f6;">Acoustic Respiratory Screening, Biomarker Analysis & Triage Directive</div>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <div style="font-size:48px;font-weight:900;color:#00e5b0;font-family:serif;line-height:1;">℞</div>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:28px 36px;">
      <table role="presentation" style="width:100%;border-collapse:collapse;background:#08101c;border:1px solid #182e4b;border-radius:12px;color:#f1f5f9;margin-bottom:24px;">
        <tr>
          <td style="padding:14px 18px;border-bottom:1px solid #182e4b;width:50%;">
            <span style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:700;">Patient ID</span><br>
            <strong style="color:#00e5b0;font-size:17px;font-family:monospace;">{escape(patient_id)}</strong>
          </td>
          <td style="padding:14px 18px;border-bottom:1px solid #182e4b;width:50%;">
            <span style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:700;">Prescription Date</span><br>
            <strong style="color:#ffffff;font-size:14px;">{escape(report_date)}</strong>
          </td>
        </tr>
        <tr>
          <td style="padding:14px 18px;">
            <span style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:700;">Patient Profile</span><br>
            <strong style="color:#ffffff;font-size:14px;">{escape(str(age))} years · {escape(str(gender).title())}</strong>
          </td>
          <td style="padding:14px 18px;">
            <span style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:700;">Prescribing Clinician</span><br>
            <strong style="color:#38bdf8;font-size:14px;">{escape(str(email or 'Dr. On-Duty (Team NOVIX)'))}</strong>
          </td>
        </tr>
      </table>
      <div style="background:#091424;border:2px solid {verdict_color};border-radius:16px;padding:24px;margin-bottom:22px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:800;letter-spacing:2px;color:#38bdf8;text-transform:uppercase;">℞ PRIMARY CLINICAL READOUT</span>
          <span style="background:{verdict_color}22;color:{verdict_color};border:1px solid {verdict_color};padding:4px 12px;border-radius:20px;font-size:12px;font-weight:800;">{escape(risk).upper()} RISK</span>
        </div>
        <div style="font-size:38px;font-weight:900;color:{verdict_color};text-transform:uppercase;margin:8px 0;">
          {verdict_icon} {escape(label)}
        </div>
      </div>
      <div style="margin-top:20px;">{result}</div>
      <div style="margin-top:20px;">{details}</div>
      <div style="margin-top:20px;">{quality_markup}</div>
      <div style="margin-top:20px;">{comparison_markup}</div>
    </div>
  </div>
</body></html>'''

    eml_text = (
        f"To: {str(email or '')}\n"
        f"Subject: {subject}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=utf-8\n"
        "Content-Transfer-Encoding: 8bit\n\n"
        f"{email_report}\n"
    )
    eml_link = f"data:message/rfc822;charset=utf-8,{quote(eml_text)}"
    html_link = f"data:text/html;charset=utf-8,{quote(email_report)}"
    pdf_path = None
    report_notice = ""

    if extended and metadata.get("label"):
        try:
            pdf_path = create_pdf_report(
                patient_id=patient_id, email=str(email or ""), age=age, gender=str(gender),
                result_html=result, details_html=details, model=str(metadata.get("model", model)),
                confidence=float(metadata.get("confidence", 0)), label=str(metadata.get("label", "Readout")),
                risk=str(metadata.get("risk", "unknown")), quality=metadata.get("quality", {}),
                comparison=metadata.get("comparison", []), chart_path=chart_path,
            )
        except Exception as exc:
            report_notice = f'<div class="notice">PDF generated locally is unavailable: {escape(str(exc))}</div>'
        try:
            save_assessment({
                "patient_id": patient_id, "date": report_date, "label": metadata.get("label", "Readout"),
                "risk": metadata.get("risk", "unknown"), "confidence": float(metadata.get("confidence", 0)),
                "age": age, "gender": str(gender), "model": metadata.get("model", model),
            })
        except Exception as exc:
            report_notice += f'<div class="notice">History save warning: {escape(str(exc))}</div>'

    reports_dir = RUNTIME_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_html_file = reports_dir / f"{patient_id}.html"
    try:
        report_html_file.write_text(email_report, encoding="utf-8")
    except Exception:
        pass

    gmail_web_link = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(str(email or ''))}&su={quote(subject)}"

    share_center_html = f'''
    <div class="share-center-wrap">
      <div class="share-center-title">
        <span>📤</span>
        <span>Multi-Channel Report Share & Export Center</span>
      </div>
      <p style="color: var(--muted); font-size: 13px; margin: 0 0 14px;">Share this clinical screening summary directly to WhatsApp, draft an email, or download verified files.</p>
      
      <div class="share-grid">
        <!-- WhatsApp Channel -->
        <div>
          <div style="font-weight: 800; font-size: 14px; color: #ffffff; margin-bottom: 6px;">
            <span style="color: #25d366;">💬</span> Share via WhatsApp
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <a class="share-action-link link-wa" href="{escape(wa_default_link)}" target="_blank">
              <span>📲 Open WhatsApp (Choose Contact)</span>
            </a>
            <div style="font-size: 11px; color: var(--muted); background: rgba(37, 211, 102, 0.08); border-left: 3px solid #25d366; padding: 6px 10px; border-radius: 6px;">
              📄 <b>WhatsApp Tip:</b> Click Open WhatsApp above, then tap 📎 <b>Attach → Document</b> to attach the PDF report!
            </div>
          </div>
        </div>

        <!-- Email & Downloads Channel -->
        <div>
          <div style="font-weight: 800; font-size: 14px; color: #ffffff; margin-bottom: 6px;">
            <span style="color: #38bdf8;">✉️</span> Share via Email & Downloads
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <a class="share-action-link link-email" href="{escape(gmail_web_link)}" target="_blank" style="background: linear-gradient(135deg, #ea4335, #c5221f); color: #fff;">
              ✉️ Open in Gmail Web (1-Click)
            </a>
            <a class="share-action-link link-email" href="{escape(email_link)}">✉️ Open email draft</a>
            <a class="share-action-link link-download" href="{escape(eml_link)}" download="novix-aerova-{escape(patient_id.lower())}.eml">📥 Download email file (.eml)</a>
            <a class="share-action-link link-download" href="{escape(html_link)}" download="novix-aerova-{escape(patient_id.lower())}.html">🌐 Download web report</a>
          </div>
        </div>
      </div>
      <p class="notification" style="margin-top: 14px;"><b>Report {escape(patient_id)}</b> created for {escape(str(email))}.</p>
      {report_notice}
    </div>
    '''

    combined_details = details + share_center_html

    if not extended:
        return (
            result, combined_details, "", None, "", None,
            history_dashboard_html(), gr.update(visible=False), gr.update(visible=True), wa_message,
            email_report, "", patient_id, str(email or ""),
        )
    return (
        result, combined_details, quality_markup, chart_path, comparison_markup,
        pdf_path, history_dashboard_html(), gr.update(visible=False), gr.update(visible=True), wa_message,
        email_report, pdf_path or "", patient_id, str(email or ""),
    )


# ---------------------------------------------------------------------------
# MAIN APP BUILDER
# ---------------------------------------------------------------------------
def build_app(predict_fn, model_files, default_model):
    captcha_question, captcha_answer = _new_captcha()

    with gr.Blocks(title="AEROVA | Respiratory Sound Check · Team NOVIX") as interface:

        # State Stores
        login_email_state = gr.State("")
        gemini_key_state = gr.State(ACTIVE_GEMINI_KEY)
        captcha_answer_state = gr.State(captcha_answer)
        wa_message_state = gr.State("")
        report_html_state = gr.State("")
        report_pdf_state = gr.State("")
        patient_id_state = gr.State("")

        # 1. Login View (The sleek hospital entrance from last version)
        with gr.Column(elem_classes=["login-shell"]) as login_view:
            gr.HTML('''<div class="login-panel">
                <div class="login-mark">AEROVA <span style="font-size: 12px; background: rgba(0,229,176,0.2); color: #00e5b0; border: 1px solid #00e5b0; padding: 2px 8px; border-radius: 12px; vertical-align: middle;">TEAM NOVIX</span></div>
                <div class="eyebrow" style="margin-top: 18px; color: var(--secondary);">Hospital Respiratory Screening</div>
                <h1 style="margin: 12px 0 6px; font-size: clamp(26px, 3vw, 40px); line-height: 1.08; color: white;">Acoustic triage for early respiratory assessment</h1>
                <p class="login-copy">Sign in to continue to the hospital-grade screening workspace for cough and respiratory symptom review.</p>
                <div class="dashboard-metrics">
                    <div class="metric-item">
                        <span class="metric-label">Active cases</span>
                        <span class="metric-value">184</span>
                        <span class="metric-trend">+12.4% this week</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Response time</span>
                        <span class="metric-value">08m</span>
                        <span class="metric-trend">Fast-track</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Emergency status</span>
                        <span class="metric-value">Level 2</span>
                        <span class="metric-trend">Monitoring</span>
                    </div>
                </div>
            </div>''')

            with gr.Row():
                fast_demo_btn = gr.Button("⚡ Instant Demo Sign-in (1-Click)", elem_classes=["demo-fast-btn"])

            gr.HTML('<div style="text-align: center; color: var(--muted); font-size: 11px; margin: 18px 0 10px; font-weight: 700; letter-spacing: 0.08em;">— OR ENTER CLINICIAN CREDENTIALS —</div>')

            login_email = gr.Textbox(label="Clinician Email", placeholder="doctor@hospital-aerova.org")
            login_password = gr.Textbox(label="Password", type="password", placeholder="8+ chars with Aa1!")
            with gr.Row(elem_classes=["captcha-row"]):
                captcha_prompt = gr.Markdown(f'<div class="captcha-question">{captcha_question}</div>')
                captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter the number", scale=2)
                captcha_refresh = gr.Button("↻", elem_classes=["secondary-button", "captcha-refresh"], scale=0)

            login_button = gr.Button("Continue securely", variant="primary", elem_classes=["primary-button"])
            login_notice = gr.HTML()
            gr.HTML('<p class="login-copy" style="font-size: 12px; margin-top: 14px; text-align: center;">Enter your email carefully. The final prescription will be addressed directly to this clinician email.</p>')

        # 2. Main Workspace (The 3-step wizard workflow)
        with gr.Column(visible=False) as workspace:
            gr.HTML('''<header class="hero hero-hospital">
                <div class="hero-left">
                    <div class="brand-banner"><span class="brand-mark">+</span><span style="font-weight: 800; letter-spacing: .08em; text-transform: uppercase;">AEROVA · TEAM NOVIX</span></div>
                    <div class="eyebrow" style="margin-top: 18px; color: rgba(255,255,255,0.84);">Hospital Respiratory Triage Unit</div>
                    <h1>Acoustic screening for early respiratory health review</h1>
                    <p>Guided assessment from recording intake to clinical risk summary, designed for a modern hospital workflow.</p>
                </div>
                <div class="hero-right">
                    <div class="status-badges">
                        <span class="portal-chip"><span class="portal-dot"></span>Live triage active</span>
                        <span class="portal-chip"><span class="portal-dot"></span>Model: Extra Trees</span>
                    </div>
                </div>
            </header>''')

            with gr.Accordion("📋 Patient history dashboard", open=False):
                with gr.Row():
                    history_search = gr.Textbox(label="Find patient ID", placeholder="Search AUR-...")
                    history_refresh = gr.Button("Search / refresh", elem_classes=["secondary-button"])
                history_output = gr.HTML(value=history_dashboard_html())

            gr.HTML('<div class="progress"><div class="progress-item active">01 · Recording</div><div class="progress-item">02 · Context</div><div class="progress-item">03 · Readout</div></div>')

            # Step 1: Bring a recording
            with gr.Column(elem_classes=["panel"]) as audio_step:
                gr.HTML('<h2 class="panel-title">Bring a recording</h2><p class="panel-copy">A short, clear 2–6 second cough recording in a quiet room works best.</p>')
                audio_input = gr.Audio(type="filepath", sources=["upload", "microphone"], label="Upload or record audio via microphone", elem_classes=["audio-box"])
                file_input = gr.File(file_count="single", label="Or choose a sound/video file (.wav, .mp3, .webm, .ogg)")
                url_input = gr.Textbox(label="Or paste a direct audio URL", placeholder="https://...")
                audio_notice = gr.HTML()
                continue_audio = gr.Button("Continue to clinical context →", variant="primary", elem_classes=["primary-button"])

            # Step 2: Add context
            with gr.Column(visible=False, elem_classes=["panel"]) as context_step:
                gr.HTML('<h2 class="panel-title">Add a little context</h2><p class="panel-copy">These details help frame the audio signal. They are optional, but useful.</p>')
                manual_notes = gr.Textbox(label="How are you feeling? (Symptoms & notes)", placeholder="For example: dry cough, fatigue, sore throat...", lines=2)
                with gr.Row():
                    gender = gr.Dropdown(["male", "female", "unknown"], label="Gender", value="unknown")
                    age = gr.Slider(0, 100, step=1, label="Patient age (years)", value=30)
                cough_detected = gr.Slider(0.0, 1.0, step=0.01, label="How likely is the sound a cough? (Confidence)", value=0.85)
                with gr.Row():
                    respiratory_condition = gr.Radio(["true", "false"], label="Pre-existing respiratory condition (Asthma / COPD)", value="false")
                    fever_muscle_pain = gr.Radio(["true", "false"], label="Fever or body pain present?", value="false")
                model_choice = gr.Dropdown(choices=model_files, value=default_model, label="Analysis model", visible=False)
                with gr.Row(elem_classes=["step-actions"]):
                    back_audio = gr.Button("← Back to recording", elem_classes=["secondary-button"])
                    predict_button = gr.Button("⚡ Generate clinical triage readout", variant="primary", elem_classes=["primary-button"])

            # Step 3: Clinical Readout
            with gr.Column(visible=False, elem_classes=["panel"]) as result_step:
                gr.HTML('<h2 class="panel-title">Your clinical readout</h2><p class="panel-copy">A clear summary of the sound and context signals, ready for follow-up or clinical review.</p>')
                prediction_output = gr.HTML()
                quality_output = gr.HTML()
                details_output = gr.HTML()

                with gr.Accordion("📊 Explainable spectrogram and confidence", open=True):
                    explanation_chart = gr.Image(label="Acoustic explanation", interactive=False)

                with gr.Accordion("🧠 Machine learning model comparison", open=False):
                    model_comparison_output = gr.HTML()

                # Dedicated WhatsApp Sharing
                with gr.Accordion("💬 Share directly via WhatsApp to Patient or Clinician", open=True):
                    with gr.Row():
                        wa_phone_input = gr.Textbox(
                            label="Recipient WhatsApp number (with Country Code)",
                            placeholder="e.g. +91 9876543210",
                            scale=3,
                        )
                        wa_send_btn = gr.Button("📲 Create WhatsApp share link", variant="primary", elem_classes=["primary-button"], scale=1)
                    wa_link_output = gr.HTML()

                # Dedicated Gmail Delivery
                with gr.Accordion("✉️ Automated Gmail & Rich Medical Prescription delivery", open=True):
                    with gr.Row():
                        email_recipient_input = gr.Textbox(
                            label="Recipient email address",
                            placeholder="doctor@hospital.org or patient@gmail.com",
                            scale=3,
                        )
                        email_sender_input = gr.Textbox(
                            label="Sender Gmail (optional)",
                            placeholder="e.g. clinic@gmail.com",
                            scale=2,
                        )
                        email_pass_input = gr.Textbox(
                            label="Google App Password (optional)",
                            placeholder="16-character App Password",
                            type="password",
                            scale=2,
                        )
                    with gr.Row():
                        send_email_now_btn = gr.Button("🚀 Send prescription email now", variant="primary", elem_classes=["primary-button"], scale=2)
                        open_gmail_compose_btn = gr.Button("✉️ Open Gmail Web compose (1-Click)", elem_classes=["secondary-button"], scale=1)
                    email_delivery_output = gr.HTML()

                pdf_report = gr.File(label="Download PDF report with verification QR", interactive=False)

                with gr.Row(elem_classes=["result-actions"]):
                    back_result = gr.Button("← Modify clinical context", elem_classes=["secondary-button"])
                    new_assessment = gr.Button("Start new assessment", elem_classes=["secondary-button"])

                gr.HTML('<div class="safety-alert" style="margin-top: 18px; padding: 16px 20px; background: rgba(244, 63, 94, 0.12); border-left: 4px solid #f43f5e; border-radius: 12px; color: #fecdd3; font-size: 13px;"><strong>When to seek urgent care:</strong> Severe breathing difficulty, chest pain, confusion, blue lips, or rapidly worsening symptoms require urgent medical attention.</div>')
                gr.HTML('<p class="footnote" style="color: var(--muted); font-size: 12px; margin-top: 12px;">This application is an acoustic screening aid developed by Team NOVIX, not a definitive medical diagnosis. Consult a clinician promptly for emergency care.</p>')

            # Floating / Bottom Assistant
            with gr.Accordion("🤖 AEROVA respiratory assistant", open=False, elem_classes=["chat-panel"]):
                gr.Markdown("Ask about the audio workflow, Healthy versus Disease results, recording quality, reports, or urgent-care guidance.")
                chatbot = gr.Chatbot(label="AEROVA assistant", height=280)
                with gr.Row():
                    chat_input = gr.Textbox(label="Message", placeholder="How does AEROVA interpret a healthy result?", scale=5)
                    chat_send = gr.Button("Ask", variant="primary", elem_classes=["primary-button"], scale=1)

        # Event Handlers
        fast_demo_btn.click(
            _fast_demo_login,
            outputs=[login_view, workspace, login_email_state, login_notice],
        )

        login_button.click(
            _demo_login,
            [login_email, login_password, captcha_entry, captcha_answer_state],
            [login_view, workspace, login_email_state, login_notice],
        )

        captcha_refresh.click(lambda: _new_captcha(), outputs=[captcha_prompt, captcha_answer_state])

        chat_send.click(_chat_response, [chat_input, chatbot], [chatbot, chat_input])
        chat_input.submit(_chat_response, [chat_input, chatbot], [chatbot, chat_input])

        history_refresh.click(history_dashboard_html, [history_search], [history_output])

        continue_audio.click(_continue_audio, [audio_input, file_input, url_input], [audio_step, context_step, audio_notice])
        back_audio.click(lambda: (gr.update(visible=True), gr.update(visible=False)), outputs=[audio_step, context_step])
        back_result.click(lambda: (gr.update(visible=False), gr.update(visible=True)), outputs=[result_step, context_step])
        new_assessment.click(
            lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", "", "", ""),
            outputs=[result_step, audio_step, context_step, prediction_output, details_output, wa_link_output, email_delivery_output],
        )

        predict_button.click(
            lambda email, *values: _run_prediction(predict_fn, email, *values),
            inputs=[login_email_state, audio_input, file_input, url_input, manual_notes, model_choice, gender, age, cough_detected, respiratory_condition, fever_muscle_pain],
            outputs=[prediction_output, details_output, quality_output, explanation_chart, model_comparison_output, pdf_report, history_output, context_step, result_step, wa_message_state, report_html_state, report_pdf_state, patient_id_state, email_recipient_input],
        )

        wa_send_btn.click(
            _generate_whatsapp_link,
            inputs=[wa_phone_input, wa_message_state],
            outputs=[wa_link_output],
        )

        send_email_now_btn.click(
            _handle_send_email_now,
            inputs=[email_recipient_input, email_sender_input, email_pass_input, patient_id_state, report_html_state, report_pdf_state],
            outputs=[email_delivery_output],
        )

        open_gmail_compose_btn.click(
            _handle_open_gmail_compose,
            inputs=[email_recipient_input, patient_id_state, wa_message_state],
            outputs=[email_delivery_output],
        )

    return interface
