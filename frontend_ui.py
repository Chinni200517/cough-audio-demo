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
import base64
from pathlib import Path
from urllib.parse import quote

import gradio as gr
import requests

from reporting import create_pdf_report, history_dashboard_html, save_assessment, send_prescription_email

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
USERS_PATH = RUNTIME_DIR / "users.json"
ASSETS_DIR = BASE_DIR / "assets"
BANNER_PATH = ASSETS_DIR / "banner.jpg"

# Global active key store (allows setting via UI, environment, or .env)
ACTIVE_GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY", "").strip()
    or os.environ.get("GOOGLE_API_KEY", "").strip()
)


def _get_banner_base64() -> str:
    if BANNER_PATH.exists():
        try:
            with open(BANNER_PATH, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""
    return ""


APP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800;900&display=swap');

:root {
  --bg-gradient: linear-gradient(135deg, #f0f7fd 0%, #e0effe 45%, #f8fafc 100%);
  --panel-bg: #ffffff;
  --navy-title: #0a2540;
  --navy-deep: #0f3b60;
  --blue-primary: #0077b6;
  --blue-vibrant: #0096c7;
  --blue-light: #e0f2fe;
  --cyan-accent: #00b4d8;
  --cyan-soft: #f0f9ff;
  --green-mint: #10b981;
  --text-main: #1e293b;
  --text-muted: #64748b;
  --shadow-lux: 0 20px 45px rgba(2, 62, 138, 0.08), 0 4px 12px rgba(2, 62, 138, 0.04);
  --shadow-card: 0 10px 30px rgba(10, 37, 64, 0.06);
}

body, .gradio-container {
  background: radial-gradient(circle at 10% 10%, #e0f2fe 0%, #f0f9ff 45%, #f8fafc 100%) !important;
  color: var(--text-main) !important;
  font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif !important;
  line-height: 1.5;
}

.gradio-container {
  max-width: 1280px !important;
  margin: auto;
  padding: 20px 18px 40px !important;
}

.gradio-container .block {
  border-radius: 20px !important;
}

/* =========================================================================
   TEXT VISIBILITY & HIGH CONTRAST (Crisp Blue Medical Theme)
   ========================================================================= */
label, label span, .gr-input-label, .block-title {
  color: var(--navy-title) !important;
  font-weight: 700 !important;
  letter-spacing: 0.01em;
}

input, textarea, select {
  background-color: #ffffff !important;
  color: var(--navy-title) !important;
  border: 1.5px solid #cbd5e1 !important;
  border-radius: 12px !important;
  padding: 10px 14px !important;
  font-size: 14px !important;
  font-weight: 500 !important;
  transition: all 0.2s ease;
}

input:focus, textarea:focus, select:focus {
  border-color: var(--blue-vibrant) !important;
  box-shadow: 0 0 0 3px rgba(0, 150, 199, 0.15) !important;
}

.primary-button {
  background: linear-gradient(135deg, #0077b6 0%, #0096c7 100%) !important;
  color: #ffffff !important;
  border: 0 !important;
  border-radius: 14px !important;
  font-weight: 800 !important;
  font-size: 15px !important;
  box-shadow: 0 10px 25px rgba(0, 119, 182, 0.25) !important;
  cursor: pointer;
  transition: all 0.2s ease;
}

.primary-button:hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
}

.secondary-button {
  border: 1.5px solid #bae6fd !important;
  color: #0284c7 !important;
  border-radius: 14px !important;
  background: #f0f9ff !important;
  font-weight: 700 !important;
  cursor: pointer;
}

.secondary-button:hover {
  background: #e0f2fe !important;
}

.demo-fast-btn {
  background: linear-gradient(135deg, #0284c7 0%, #0077b6 100%) !important;
  color: #ffffff !important;
  font-weight: 800 !important;
  font-size: 16px !important;
  border-radius: 14px !important;
  padding: 15px 24px !important;
  box-shadow: 0 12px 30px rgba(2, 132, 199, 0.3) !important;
  border: none !important;
  cursor: pointer;
  width: 100%;
}

.demo-fast-btn:hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
}

/* =========================================================================
   PANELS & CARDS
   ========================================================================= */
.panel {
  background: #ffffff !important;
  border: 1.5px solid rgba(2, 132, 199, 0.16) !important;
  border-radius: 22px !important;
  padding: 26px 30px !important;
  box-shadow: var(--shadow-lux) !important;
  margin-top: 14px;
}

.panel-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--navy-title);
  margin: 0 0 4px;
  letter-spacing: -0.02em;
}

.panel-copy {
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1.5;
  margin: 0 0 18px;
}

/* =========================================================================
   POSTER SHOWCASE & COMPANY NAME HERO
   ========================================================================= */
.poster-hero-card {
  background: linear-gradient(135deg, #ffffff 0%, #f0f9ff 100%);
  border: 2px solid rgba(0, 150, 199, 0.25);
  border-radius: 24px;
  padding: 30px 34px;
  box-shadow: var(--shadow-lux);
  margin-bottom: 24px;
}

.poster-top-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
}

.project-kicker {
  display: inline-block;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #0284c7;
  margin-bottom: 6px;
}

.project-brand-title {
  font-size: clamp(38px, 5.5vw, 62px);
  font-weight: 900;
  line-height: 1.0;
  letter-spacing: -0.03em;
  color: var(--navy-title);
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.project-brand-tagline {
  font-size: clamp(17px, 2.2vw, 24px);
  font-weight: 700;
  color: #0077b6;
  margin: 0 0 14px;
}

.team-novix-box {
  background: #ffffff;
  border: 2.5px solid #0096c7;
  border-radius: 20px;
  padding: 20px 28px;
  box-shadow: 0 12px 30px rgba(0, 150, 199, 0.14);
  text-align: center;
}

.team-novix-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #0284c7;
  margin-bottom: 2px;
}

.team-novix-title {
  font-size: clamp(40px, 5vw, 54px);
  font-weight: 900;
  color: var(--navy-title);
  line-height: 1;
  letter-spacing: -0.02em;
}

/* Three Pillars Feature Grid from Poster */
.poster-pillars-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin: 24px 0 20px;
}

.pillar-card {
  background: #ffffff;
  border: 1.5px solid rgba(2, 132, 199, 0.18);
  border-radius: 18px;
  padding: 22px 20px;
  box-shadow: var(--shadow-card);
  transition: all 0.2s ease;
}

.pillar-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 30px rgba(2, 62, 138, 0.1);
  border-color: #0096c7;
}

.pillar-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0096c7, #0077b6);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 22px;
  margin-bottom: 14px;
  box-shadow: 0 8px 20px rgba(0, 119, 182, 0.25);
}

.pillar-title {
  font-size: 17px;
  font-weight: 800;
  color: var(--navy-title);
  margin-bottom: 6px;
}

.pillar-desc {
  font-size: 13.5px;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0;
}

/* Team Members Footer Bar from Poster */
.team-members-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
  background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%);
  border: 1.5px solid rgba(2, 132, 199, 0.22);
  border-radius: 16px;
  padding: 14px 22px;
  margin-top: 20px;
}

.members-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #0077b6;
}

.member-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--navy-title);
}

.member-roll {
  font-size: 11.5px;
  font-weight: 700;
  color: #0284c7;
  background: #ffffff;
  padding: 3px 10px;
  border-radius: 8px;
  border: 1px solid rgba(2, 132, 199, 0.25);
}

/* =========================================================================
   LOGIN PANEL
   ========================================================================= */
.login-panel {
  max-width: 600px;
  margin: 20px auto 40px;
  padding: 36px 34px;
  background: #ffffff;
  border: 2px solid rgba(0, 150, 199, 0.28);
  border-radius: 24px;
  box-shadow: 0 20px 50px rgba(0, 119, 182, 0.12);
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 22px;
}

.metric-item {
  background: #f0f9ff;
  border: 1.5px solid rgba(2, 132, 199, 0.2);
  border-radius: 16px;
  padding: 14px 12px;
  text-align: center;
}

.metric-label {
  display: block;
  font: 800 10px 'Plus Jakarta Sans', sans-serif;
  color: #0284c7;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 6px;
  font: 800 24px/1 'Plus Jakarta Sans', sans-serif;
  color: var(--navy-title);
}

.metric-trend {
  display: inline-block;
  margin-top: 6px;
  font: 700 11px Arial, sans-serif;
  color: #10b981;
}

/* =========================================================================
   HERO HEADER & PROGRESS WIZARD
   ========================================================================= */
.hero {
  padding: 26px 32px 22px;
  border: 1.5px solid rgba(2, 132, 199, 0.2);
  background: linear-gradient(135deg, #0077b6 0%, #0096c7 50%, #023e8a 100%);
  border-radius: 24px;
  color: #ffffff;
  box-shadow: 0 20px 45px rgba(2, 62, 138, 0.18);
}

.hero-hospital {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 150px;
}

.hero-left {
  max-width: 70%;
}

.hero-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-end;
}

.hero h1 {
  margin: 10px 0 6px;
  font-size: clamp(26px, 3.8vw, 44px);
  line-height: 1.05;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #ffffff;
}

.hero p {
  max-width: 680px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 15px;
  line-height: 1.5;
  margin: 0;
}

.brand-banner {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 999px;
  padding: 8px 16px;
  backdrop-filter: blur(6px);
}

.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #ffffff;
  color: #0077b6;
  font-weight: 900;
  font-size: 16px;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
}

.portal-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: #ffffff;
  border-radius: 999px;
  padding: 8px 14px;
  font: 800 11px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.portal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.9);
}

.progress {
  display: flex;
  gap: 12px;
  margin: 20px 0;
}

.progress-item {
  flex: 1;
  border-top: 4px solid #cbd5e1;
  padding-top: 10px;
  color: #64748b;
  font: 800 11.5px 'Plus Jakarta Sans', sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  transition: all 0.2s ease;
}

.progress-item.active {
  color: #0077b6;
  border-color: #0077b6;
}

.audio-box {
  border: 2px dashed #0096c7;
  background: #f0f9ff;
  border-radius: 18px;
  padding: 10px;
}

.captcha-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.captcha-question {
  color: #0077b6;
  font: 800 15px Arial, sans-serif;
  padding: 12px 16px;
  background: #e0f2fe;
  border: 1px solid #bae6fd;
  border-radius: 12px;
}

.notice {
  color: #dc2626;
  font: 700 13px Arial, sans-serif;
  padding: 10px 0;
}

.notification {
  color: #0284c7;
  font: 700 13px Arial, sans-serif;
  margin-top: 10px;
}

.share-center-wrap {
  background: #ffffff;
  border: 1.5px solid rgba(2, 132, 199, 0.25);
  border-radius: 22px;
  padding: 24px 28px;
  margin: 20px 0;
  box-shadow: 0 16px 40px rgba(2, 62, 138, 0.08);
}

.share-center-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 800;
  color: var(--navy-title);
  margin-bottom: 6px;
}

.share-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 14px;
}

.share-action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 18px;
  border-radius: 12px;
  font-weight: 800;
  font-size: 13.5px;
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
  background: #0284c7;
  color: #ffffff !important;
}

.link-download {
  background: #f0f9ff;
  color: #0284c7 !important;
  border: 1.5px solid #bae6fd;
}

@media (max-width: 768px) {
  .poster-pillars-grid {
    grid-template-columns: 1fr;
  }
  .share-grid {
    grid-template-columns: 1fr;
  }
  .team-members-bar {
    flex-direction: column;
    align-items: flex-start;
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
    if "who made" in lowered or "author" in lowered or "team" in lowered or "developer" in lowered or "novix" in lowered:
        return "AEROVA was developed by Chinni200517 for Team Novix (Chinni Krishna B, Hemashree D G, Pruthvi N) as an acoustic respiratory clinical triage system."
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
        answer = "AEROVA by Team Novix analyses acoustic cough patterns using ensemble machine learning models to detect respiratory infection signals. It is a screening aid, not emergency care."

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
        f"🏥 *NOVIX AEROVA - DIGITAL CLINICAL PRESCRIPTION (Rx)*\n"
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
        return '<div class="notice">⚠️ Please run assessment to generate clinical report first.</div>'
    encoded_msg = quote(str(wa_message_text))
    if phone_clean:
        wa_url = f"https://wa.me/{phone_clean}?text={encoded_msg}"
        target_desc = f"+{phone_clean}"
    else:
        wa_url = f"https://wa.me/?text={encoded_msg}"
        target_desc = "your selected contact / patient"

    return f'''
    <div style="margin-top: 10px; background: #f0fdf4; border: 1.5px solid #25d366; border-radius: 14px; padding: 16px 20px;">
      <div style="color: #166534; font-weight: 800; font-size: 13.5px; margin-bottom: 6px;">💬 WhatsApp Share Link Ready:</div>
      <a href="{escape(wa_url)}" target="_blank" class="share-action-link link-wa" style="font-size: 14px; font-weight: 800; padding: 12px 22px;">
        🚀 Click to Open WhatsApp & Share via WhatsApp
      </a>
      <div style="color: #475569; font-size: 11.5px; margin-top: 8px;">Tip: Once WhatsApp opens, tap <b>Attach 📎 → Document</b> to attach your downloaded PDF report!</div>
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
        f'<div style="margin-top: 10px; background: #f0f9ff; border: 1.5px solid #0284c7; border-radius: 14px; padding: 16px 20px;">'
        f'<div style="color: #0284c7; font-weight: 800; font-size: 13.5px; margin-bottom: 6px;">✉️ Gmail Web Compose Ready:</div>'
        f'<a href="{escape(gmail_url)}" target="_blank" class="share-action-link link-email" style="font-size: 14px; font-weight: 800; padding: 12px 24px; background: linear-gradient(135deg, #ea4335, #c5221f); color: #fff;">'
        f'🚀 Click to Open in Gmail Compose</a>'
        f'<div style="color: #64748b; font-size: 11.5px; margin-top: 6px;">Opens Gmail in a new tab with recipient, subject, and prescription pre-filled.</div>'
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

    verdict_color = "#0284c7" if label == "Healthy" else "#dc2626"
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
<body style="margin:0;background:#f0f7fd;font-family:'Segoe UI',Arial,sans-serif;color:#1e293b;padding:24px;">
  <div style="max-width:780px;margin:0 auto;background:#ffffff;border:2px solid #0096c7;border-radius:22px;overflow:hidden;box-shadow:0 20px 60px rgba(2,62,138,0.14);">
    <div style="background:linear-gradient(135deg,#0077b6,#023e8a);padding:32px 38px;color:#ffffff;">
      <table role="presentation" style="width:100%;border-collapse:collapse;">
        <tr>
          <td>
            <div style="font-size:12px;letter-spacing:2.5px;font-weight:800;text-transform:uppercase;color:#90e0ef;">TEAM NOVIX · DIGITAL CLINICAL CARE</div>
            <h1 style="margin:8px 0 4px;font-size:32px;font-weight:900;color:#ffffff;">AEROVA DIGITAL CLINICAL PRESCRIPTION</h1>
            <div style="font-size:14px;color:#e0f2fe;">Listen. Detect. Breathe Better. · Acoustic Respiratory Screening</div>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <div style="font-size:48px;font-weight:900;color:#ffffff;font-family:serif;line-height:1;">℞</div>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:30px 38px;">
      <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc;border:1.5px solid #e2e8f0;border-radius:14px;color:#1e293b;margin-bottom:24px;">
        <tr>
          <td style="padding:14px 18px;border-bottom:1px solid #e2e8f0;width:50%;">
            <span style="font-size:11px;text-transform:uppercase;color:#64748b;font-weight:800;">Patient ID</span><br>
            <strong style="color:#0077b6;font-size:17px;font-family:monospace;">{escape(patient_id)}</strong>
          </td>
          <td style="padding:14px 18px;border-bottom:1px solid #e2e8f0;width:50%;">
            <span style="font-size:11px;text-transform:uppercase;color:#64748b;font-weight:800;">Prescription Date</span><br>
            <strong style="color:#0a2540;font-size:14px;">{escape(report_date)}</strong>
          </td>
        </tr>
        <tr>
          <td style="padding:14px 18px;">
            <span style="font-size:11px;text-transform:uppercase;color:#64748b;font-weight:800;">Patient Profile</span><br>
            <strong style="color:#0a2540;font-size:14px;">{escape(str(age))} years · {escape(str(gender).title())}</strong>
          </td>
          <td style="padding:14px 18px;">
            <span style="font-size:11px;text-transform:uppercase;color:#64748b;font-weight:800;">Prescribing Clinician</span><br>
            <strong style="color:#0284c7;font-size:14px;">{escape(str(email or 'Dr. On-Duty (Team NOVIX)'))}</strong>
          </td>
        </tr>
      </table>
      <div style="background:#ffffff;border:2px solid {verdict_color};border-radius:16px;padding:24px;margin-bottom:22px;box-shadow:0 10px 25px rgba(2,62,138,0.06);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:800;letter-spacing:2px;color:#0077b6;text-transform:uppercase;">℞ PRIMARY CLINICAL READOUT</span>
          <span style="background:#e0f2fe;color:{verdict_color};border:1.5px solid {verdict_color};padding:4px 14px;border-radius:20px;font-size:12px;font-weight:800;">{escape(risk).upper()} RISK</span>
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
      <p style="color: var(--text-muted); font-size: 13.5px; margin: 0 0 14px;">Share this clinical screening summary directly to WhatsApp, draft an email, or download verified files.</p>
      
      <div class="share-grid">
        <!-- WhatsApp Channel -->
        <div>
          <div style="font-weight: 800; font-size: 14px; color: var(--navy-title); margin-bottom: 6px;">
            <span style="color: #25d366;">💬</span> Share via WhatsApp
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <a class="share-action-link link-wa" href="{escape(wa_default_link)}" target="_blank">
              <span>📲 Open WhatsApp & Share via WhatsApp</span>
            </a>
            <div style="font-size: 11.5px; color: #475569; background: #f0fdf4; border-left: 3px solid #25d366; padding: 6px 10px; border-radius: 6px;">
              📄 <b>WhatsApp Tip:</b> Click Open WhatsApp above, then tap 📎 <b>Attach → Document</b> to attach the PDF report!
            </div>
          </div>
        </div>

        <!-- Email & Downloads Channel -->
        <div>
          <div style="font-weight: 800; font-size: 14px; color: var(--navy-title); margin-bottom: 6px;">
            <span style="color: #0284c7;">✉️</span> Share via Email & Downloads
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
    banner_b64 = _get_banner_base64()

    poster_img_tag = (
        f'<div style="text-align: center; margin: 10px 0 24px;">'
        f'<img src="data:image/jpeg;base64,{banner_b64}" alt="AEROVA Team Novix" '
        f'style="width: 100%; max-width: 980px; border-radius: 22px; box-shadow: 0 16px 45px rgba(2, 62, 138, 0.16); border: 2.5px solid #e0f2fe; display: block; margin: 0 auto;" />'
        f'</div>'
    ) if banner_b64 else ""

    with gr.Blocks(title="AEROVA · TEAM NOVIX | Listen. Detect. Breathe Better.") as interface:

        # State Stores
        login_email_state = gr.State("")
        gemini_key_state = gr.State(ACTIVE_GEMINI_KEY)
        captcha_answer_state = gr.State(captcha_answer)
        wa_message_state = gr.State("")
        report_html_state = gr.State("")
        report_pdf_state = gr.State("")
        patient_id_state = gr.State("")

        # 1. Entrance / Login View (The Poster-themed Blue Medical Showcase)
        with gr.Column(elem_classes=["login-shell"]) as login_view:

            # Top Poster Showcase Card
            gr.HTML(f'''
            <div class="poster-hero-card">
              <!-- Top Row: Project Title + Big Team Name -->
              <div class="poster-top-row">
                <div class="poster-title-area">
                  <span class="project-kicker">PROJECT TITLE</span>
                  <div class="project-brand-title">
                    <span>AEROVA</span>
                    <span style="font-size: 38px; color: #0096c7;">💨</span>
                  </div>
                  <div class="project-brand-tagline">Listen. Detect. Breathe Better.</div>
                  <p style="color: #64748b; font-size: 14px; margin: 0; line-height: 1.5;">
                    State-of-the-art acoustic triage platform powered by 10 ensemble machine learning classifiers, 
                    deep MFCC biomarker extraction, and automated clinical prescriptions.
                  </p>
                </div>

                <!-- Big Attractive Company / Team Name -->
                <div class="team-novix-box">
                  <div class="team-novix-label">TEAM NAME</div>
                  <div class="team-novix-title">Novix</div>
                  <div style="font-size: 11.5px; font-weight: 700; color: #0077b6; margin-top: 4px; letter-spacing: 0.05em;">
                    PULMONARY AI INNOVATION
                  </div>
                </div>
              </div>

              <!-- Embedded Official Poster Graphic -->
              {poster_img_tag}

              <!-- 3 Core Pillars from the Poster -->
              <div class="poster-pillars-grid">
                <div class="pillar-card">
                  <div class="pillar-icon-wrap">🎙️</div>
                  <div class="pillar-title">1. Smart Cough Detection</div>
                  <p class="pillar-desc">Uses AI to analyze cough patterns and track acoustic frequency and intensity with high precision.</p>
                </div>

                <div class="pillar-card">
                  <div class="pillar-icon-wrap">🛡️</div>
                  <div class="pillar-title">2. Personalized Health Insights</div>
                  <p class="pillar-desc">Provides actionable clinical insights and recommendations for better respiratory health and recovery.</p>
                </div>

                <div class="pillar-card">
                  <div class="pillar-icon-wrap">📱</div>
                  <div class="pillar-title">3. Easy & Accessible</div>
                  <p class="pillar-desc">Seamless web and mobile experience to monitor, manage, and improve your breathing anywhere, anytime.</p>
                </div>
              </div>

              <!-- Team Members Bar from Poster -->
              <div class="team-members-bar">
                <div class="members-tag">
                  <span>👥</span>
                  <span>TEAM MEMBERS</span>
                </div>
                <div class="member-item">
                  <span>👤 Chinni Krishna B</span>
                  <span class="member-roll">1JB25MC013</span>
                </div>
                <div class="member-item">
                  <span>👤 Hemashree D G</span>
                  <span class="member-roll">1JB25MC021</span>
                </div>
                <div class="member-item">
                  <span>👤 Pruthvi N</span>
                  <span class="member-roll">1JB25MC037</span>
                </div>
              </div>
            </div>
            ''')

            # The Clean Login Card
            gr.HTML('''
            <div class="login-panel">
              <div style="text-align: center; margin-bottom: 20px;">
                <div style="font-size: 12px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #0284c7; margin-bottom: 4px;">
                  CLINICAL ACCESS GATE
                </div>
                <h2 style="font-size: 26px; font-weight: 900; color: #0a2540; margin: 0 0 6px;">Sign In to Team Novix Workspace</h2>
                <p style="color: #64748b; font-size: 13.5px; margin: 0;">Access the acoustic triage platform for cough analysis and clinical report generation.</p>
              </div>

              <div class="dashboard-metrics">
                <div class="metric-item">
                  <span class="metric-label">Active cases</span>
                  <span class="metric-value">184</span>
                  <span class="metric-trend">● Live Monitoring</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">Model Accuracy</span>
                  <span class="metric-value">85.7%</span>
                  <span class="metric-trend">Extra Trees</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">Emergency status</span>
                  <span class="metric-value">Level 2</span>
                  <span class="metric-trend">ER Watch Active</span>
                </div>
              </div>
            </div>
            ''')

            with gr.Column(elem_classes=["login-panel"], scale=1):
                # Instant 1-Click Demo Sign-in
                fast_demo_btn = gr.Button("⚡ Instant Demo Sign-in (1-Click)", elem_classes=["demo-fast-btn"])

                gr.HTML('<div style="text-align: center; color: #64748b; font-size: 11.5px; margin: 18px 0 12px; font-weight: 800; letter-spacing: 0.08em;">— OR ENTER CLINICIAN CREDENTIALS —</div>')

                login_email = gr.Textbox(label="Clinician Email", placeholder="doctor@hospital-aerova.org")
                login_password = gr.Textbox(label="Password", type="password", placeholder="8+ chars with Aa1!")
                with gr.Row(elem_classes=["captcha-row"]):
                    captcha_prompt = gr.Markdown(f'<div class="captcha-question">{captcha_question}</div>')
                    captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter the number", scale=2)
                    captcha_refresh = gr.Button("↻", elem_classes=["secondary-button", "captcha-refresh"], scale=0)

                login_button = gr.Button("Continue Securely", variant="primary", elem_classes=["primary-button"])
                login_notice = gr.HTML()
                gr.HTML('<p style="color: #64748b; font-size: 12px; margin-top: 14px; text-align: center;">Enter your email carefully. The final prescription will be addressed directly to this clinician email.</p>')

        # 2. Main Workspace (Guided 3-step wizard workflow in the Blue Medical Theme)
        with gr.Column(visible=False) as workspace:
            gr.HTML('''
            <header class="hero hero-hospital">
                <div class="hero-left">
                    <div class="brand-banner">
                      <span class="brand-mark">✦</span>
                      <span style="font-weight: 800; letter-spacing: .08em; text-transform: uppercase;">AEROVA · TEAM NOVIX</span>
                    </div>
                    <div style="font-size: 12px; font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase; color: #90e0ef; margin-top: 14px;">
                      Listen. Detect. Breathe Better.
                    </div>
                    <h1>Acoustic Screening for Early Respiratory Health Review</h1>
                    <p>Guided assessment from recording intake to clinical risk summary, designed by Team Novix for a modern hospital workflow.</p>
                </div>
                <div class="hero-right">
                    <div style="display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end;">
                        <span class="portal-chip"><span class="portal-dot"></span>Live Triage Active</span>
                        <span class="portal-chip"><span class="portal-dot"></span>Model: Extra Trees</span>
                    </div>
                    <div style="font-size: 12px; color: #e0f2fe; text-align: right; margin-top: 6px;">
                      Team: Chinni Krishna B · Hemashree D G · Pruthvi N
                    </div>
                </div>
            </header>
            ''')

            with gr.Accordion("📋 Patient history dashboard", open=False):
                with gr.Row():
                    history_search = gr.Textbox(label="Find patient ID", placeholder="Search AUR-...")
                    history_refresh = gr.Button("Search / refresh", elem_classes=["secondary-button"])
                history_output = gr.HTML(value=history_dashboard_html())

            gr.HTML('''
            <div class="progress">
              <div class="progress-item active">01 · Cough Audio Intake</div>
              <div class="progress-item">02 · Clinical Context</div>
              <div class="progress-item">03 · Readout & Prescription</div>
            </div>
            ''')

            # Step 1: Bring a recording
            with gr.Column(elem_classes=["panel"]) as audio_step:
                gr.HTML('<h2 class="panel-title">1. Bring a Cough Recording</h2><p class="panel-copy">A short, clear 2–6 second cough recording in a quiet room produces the most reliable acoustic biomarkers.</p>')
                audio_input = gr.Audio(type="filepath", sources=["upload", "microphone"], label="Upload or record audio via microphone", elem_classes=["audio-box"])
                file_input = gr.File(file_count="single", label="Or choose an audio/video file (.wav, .mp3, .webm, .ogg)")
                url_input = gr.Textbox(label="Or paste a direct audio URL", placeholder="https://...")
                audio_notice = gr.HTML()
                continue_audio = gr.Button("Continue to Clinical Context →", variant="primary", elem_classes=["primary-button"])

            # Step 2: Add context
            with gr.Column(visible=False, elem_classes=["panel"]) as context_step:
                gr.HTML('<h2 class="panel-title">2. Add Patient & Clinical Context</h2><p class="panel-copy">Clinical context details help frame the audio signal and enhance machine learning classification.</p>')
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
                    back_audio = gr.Button("← Back to Recording", elem_classes=["secondary-button"])
                    predict_button = gr.Button("⚡ Generate Clinical Triage Readout", variant="primary", elem_classes=["primary-button"])

            # Step 3: Clinical Readout
            with gr.Column(visible=False, elem_classes=["panel"]) as result_step:
                gr.HTML('<h2 class="panel-title">3. Clinical Readout & Multi-Channel Sharing</h2><p class="panel-copy">A comprehensive summary of acoustic biomarkers, model conviction, and actionable clinical directives.</p>')
                prediction_output = gr.HTML()
                quality_output = gr.HTML()
                details_output = gr.HTML()

                with gr.Accordion("📊 Explainable Spectrogram & Waveform", open=True):
                    explanation_chart = gr.Image(label="Acoustic explanation", interactive=False)

                with gr.Accordion("🧠 Machine Learning Model Benchmark Comparison", open=False):
                    model_comparison_output = gr.HTML()

                # Dedicated WhatsApp Sharing
                with gr.Accordion("💬 Share Directly via WhatsApp to Patient or Clinician", open=True):
                    with gr.Row():
                        wa_phone_input = gr.Textbox(
                            label="Recipient WhatsApp number (with Country Code)",
                            placeholder="e.g. +91 9876543210",
                            scale=3,
                        )
                        wa_send_btn = gr.Button("📲 Create WhatsApp Share Link", variant="primary", elem_classes=["primary-button"], scale=1)
                    wa_link_output = gr.HTML()

                # Dedicated Gmail Delivery
                with gr.Accordion("✉️ Automated Gmail & Rich Medical Prescription Delivery", open=True):
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
                        send_email_now_btn = gr.Button("🚀 Send Prescription Email Now", variant="primary", elem_classes=["primary-button"], scale=2)
                        open_gmail_compose_btn = gr.Button("✉️ Open Gmail Web Compose (1-Click)", elem_classes=["secondary-button"], scale=1)
                    email_delivery_output = gr.HTML()

                pdf_report = gr.File(label="Download Verified PDF Report (with QR Authentication)", interactive=False)

                with gr.Row(elem_classes=["result-actions"]):
                    back_result = gr.Button("← Modify Clinical Context", elem_classes=["secondary-button"])
                    new_assessment = gr.Button("Start New Assessment", elem_classes=["secondary-button"])

                gr.HTML('<div class="safety-alert" style="margin-top: 18px; padding: 16px 20px; background: #fee2e2; border-left: 4px solid #ef4444; border-radius: 14px; color: #991b1b; font-size: 13.5px;"><strong>When to seek urgent care:</strong> Severe breathing difficulty, chest pain, confusion, blue lips, or rapidly worsening symptoms require immediate emergency medical attention.</div>')
                gr.HTML('<p class="footnote" style="color: var(--text-muted); font-size: 12px; margin-top: 12px;">This application is an acoustic screening aid developed by Team Novix, not a definitive medical diagnosis. Consult a clinician promptly for emergency care.</p>')

            # Floating / Bottom Assistant
            with gr.Accordion("🤖 AEROVA-BOT · AI Respiratory Copilot", open=False, elem_classes=["chat-panel"]):
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
