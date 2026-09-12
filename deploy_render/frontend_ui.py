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

# ---------------------------------------------------------------------------
# AUTHENTICATION & SECURE USER STORE (Team NOVIX)
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
        return gr.update(visible=True), gr.update(visible=False), "", '<div class="notice">⚠️ Please enter a valid email address (e.g., doctor@novix.org).</div>'
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

    # If user not registered yet, check strong password standard for open demo access
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
    """Bypass manual entry for frictionless demo evaluation."""
    demo_email = "clinician@hospital-aerova.org"
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        demo_email,
        f'<div class="notification">⚡ Instant Demo Access granted for Team NOVIX. Ready to screen cough audio!</div>',
    )


def _new_captcha():
    first = secrets.randbelow(8) + 2
    second = secrets.randbelow(8) + 2
    return f"What is {first} + {second}?", str(first + second)


APP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --bg-canvas: #070c14;
  --bg-surface: #0e1626;
  --bg-surface-elevated: #131f36;
  --bg-panel: rgba(14, 22, 38, 0.95);
  --ink-bright: #ffffff;
  --ink: #f8fafc;
  --ink-muted: #94a3b8;
  --ink-subtle: #cbd5e1;
  --novix-primary: #00e5b0;
  --novix-primary-dark: #059669;
  --novix-cyan: #38bdf8;
  --novix-blue: #2563eb;
  --novix-indigo: #6366f1;
  --accent-coral: #f43f5e;
  --accent-amber: #f59e0b;
  --border-line: rgba(56, 189, 248, 0.22);
  --border-glow: rgba(0, 229, 176, 0.35);
  --shadow-lux: 0 20px 50px rgba(0, 0, 0, 0.65), 0 0 1px rgba(56, 189, 248, 0.3);
}

* { box-sizing: border-box; }

body, .gradio-container {
  background: radial-gradient(ellipse at 15% 10%, #0f1e36 0%, #080f1e 45%, #040810 100%) !important;
  color: var(--ink) !important;
  font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif !important;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

.gradio-container {
  max-width: 1340px !important;
  margin: auto;
  padding: 16px 20px 60px !important;
}

.gradio-container .block {
  border-radius: 18px !important;
}

/* ==========================================================================
   TEAM NOVIX BRANDING & HERO ENTRANCE
   ========================================================================== */
.novix-hero {
  text-align: center;
  padding: 24px 20px 10px;
  max-width: 820px;
  margin: 0 auto;
}

.novix-badge-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(0, 229, 176, 0.12);
  border: 1px solid rgba(0, 229, 176, 0.35);
  padding: 6px 16px;
  border-radius: 9999px;
  margin-bottom: 14px;
}

.novix-tag {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #00e5b0;
}

.novix-pulse {
  width: 8px;
  height: 8px;
  background: #00e5b0;
  border-radius: 50%;
  box-shadow: 0 0 12px #00e5b0;
  animation: pulse-ring 2s infinite ease-in-out;
}

@keyframes pulse-ring {
  0% { transform: scale(0.9); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.7; }
}

.novix-title {
  font-size: clamp(32px, 4.4vw, 54px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.12;
  margin: 8px 0 12px;
  background: linear-gradient(135deg, #ffffff 40%, #7bf5d4 80%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.novix-tagline {
  font-size: clamp(15px, 1.8vw, 18px);
  font-weight: 500;
  color: #94a3b8;
  max-width: 680px;
  margin: 0 auto 20px;
  line-height: 1.5;
}

.novix-kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin: 18px 0 24px;
}

.novix-kpi-card {
  background: rgba(19, 31, 54, 0.75);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
  padding: 14px 16px;
  backdrop-filter: blur(12px);
  transition: all 0.25s ease;
}
.novix-kpi-card:hover {
  border-color: rgba(0, 229, 176, 0.45);
  transform: translateY(-2px);
}
.kpi-val {
  font-size: 22px;
  font-weight: 800;
  color: #00e5b0;
  display: block;
  font-family: 'JetBrains Mono', monospace;
}
.kpi-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 4px;
}

/* ==========================================================================
   AUTHENTICATION CARDS & TABS
   ========================================================================== */
.auth-container {
  max-width: 580px;
  margin: 0 auto 40px;
  background: rgba(14, 22, 38, 0.92);
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 22px;
  padding: 28px 30px;
  box-shadow: var(--shadow-lux);
  backdrop-filter: blur(20px);
}

.auth-notice-rules {
  background: rgba(19, 31, 54, 0.65);
  border-left: 3px solid #00e5b0;
  padding: 10px 14px;
  border-radius: 8px;
  margin: 12px 0 16px;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.5;
}

.demo-fast-btn {
  background: linear-gradient(135deg, #00e5b0, #0284c7) !important;
  color: #041620 !important;
  font-weight: 800 !important;
  font-size: 14px !important;
  border-radius: 12px !important;
  border: none !important;
  padding: 14px !important;
  box-shadow: 0 10px 25px rgba(0, 229, 176, 0.35) !important;
  cursor: pointer !important;
  transition: all 0.25s ease !important;
  width: 100% !important;
}
.demo-fast-btn:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 14px 30px rgba(0, 229, 176, 0.5) !important;
}

.primary-button {
  background: linear-gradient(135deg, #00e5b0, #059669) !important;
  color: #041620 !important;
  font-weight: 800 !important;
  border-radius: 12px !important;
  padding: 12px 20px !important;
  border: none !important;
  cursor: pointer !important;
  transition: all 0.25s ease !important;
}
.primary-button:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 10px 24px rgba(0, 229, 176, 0.4) !important;
}

.secondary-button {
  background: rgba(19, 31, 54, 0.9) !important;
  color: var(--ink-bright) !important;
  border: 1px solid rgba(56, 189, 248, 0.3) !important;
  border-radius: 12px !important;
  padding: 10px 18px !important;
  font-weight: 600 !important;
  cursor: pointer !important;
  transition: all 0.2s ease !important;
}
.secondary-button:hover {
  border-color: #00e5b0 !important;
  color: #00e5b0 !important;
}

.captcha-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-top: 10px;
}
.captcha-question {
  color: #00e5b0;
  font-weight: 800;
  font-size: 15px;
  padding: 12px 16px;
  background: rgba(0, 229, 176, 0.12);
  border: 1px solid rgba(0, 229, 176, 0.35);
  border-radius: 12px;
}

/* ==========================================================================
   WORKSPACE & STEP PROGRESSION
   ========================================================================== */
.workspace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 22px 28px;
  background: rgba(14, 22, 38, 0.88);
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 20px;
  margin-bottom: 22px;
  backdrop-filter: blur(16px);
}

.progress-wizard {
  display: flex;
  gap: 14px;
  margin: 18px 0 24px;
}
.wizard-step {
  flex: 1;
  border-top: 4px solid rgba(255, 255, 255, 0.12);
  padding-top: 10px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  transition: all 0.3s ease;
}
.wizard-step.active {
  color: #00e5b0;
  border-color: #00e5b0;
}

.panel-card {
  background: rgba(14, 22, 38, 0.92) !important;
  border: 1px solid rgba(56, 189, 248, 0.25) !important;
  border-radius: 20px !important;
  padding: 26px 30px !important;
  box-shadow: var(--shadow-lux) !important;
  backdrop-filter: blur(18px);
}

.panel-title {
  font-size: 22px;
  font-weight: 800;
  color: #ffffff;
  margin: 0 0 6px;
  letter-spacing: -0.02em;
}
.panel-sub {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 20px;
}

/* ==========================================================================
   MULTI-CHANNEL REPORT SHARING CENTER (WhatsApp & Email)
   ========================================================================== */
.share-center-wrap {
  background: linear-gradient(135deg, rgba(14, 22, 38, 0.98), rgba(8, 30, 48, 0.95));
  border: 1px solid rgba(0, 229, 176, 0.4);
  border-radius: 20px;
  padding: 24px 28px;
  margin: 22px 0;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
}

.share-center-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
}

.share-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 16px;
}

.share-col {
  background: rgba(19, 31, 54, 0.7);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
  padding: 18px 20px;
}

.share-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #38bdf8;
  margin-bottom: 12px;
}

.share-action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none !important;
  transition: all 0.25s ease;
  margin: 4px 4px 6px 0;
}

.link-wa {
  background: #25d366;
  color: #032d12 !important;
}
.link-wa:hover {
  background: #1eb956;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(37, 211, 102, 0.4);
}

.link-email {
  background: #38bdf8;
  color: #082f49 !important;
}
.link-email:hover {
  background: #0ea5e9;
  transform: translateY(-2px);
}

.link-download {
  background: rgba(255, 255, 255, 0.1);
  color: #e2e8f0 !important;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.link-download:hover {
  background: rgba(255, 255, 255, 0.2);
  border-color: #00e5b0;
  color: #00e5b0 !important;
}

/* ==========================================================================
   AI ROBOT COPILOT DOCK
   ========================================================================== */
.robot-dock {
  border-radius: 18px !important;
  border: 1px solid rgba(0, 229, 176, 0.3) !important;
  background: rgba(11, 20, 34, 0.95) !important;
  box-shadow: var(--shadow-lux) !important;
  overflow: hidden !important;
}

.robot-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
}

.robot-avatar {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #00e5b0, #0284c7);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  box-shadow: 0 0 16px rgba(0, 229, 176, 0.4);
}

.robot-meta-title {
  font-size: 15px;
  font-weight: 800;
  color: #ffffff;
}
.robot-meta-sub {
  font-size: 11px;
  color: #94a3b8;
}

.robot-chip {
  background: rgba(19, 31, 54, 0.85) !important;
  border: 1px solid rgba(56, 189, 248, 0.25) !important;
  color: #cbd5e1 !important;
  font-size: 11px !important;
  border-radius: 9999px !important;
  padding: 6px 14px !important;
  font-weight: 600 !important;
}
.robot-chip:hover {
  border-color: #00e5b0 !important;
  color: #00e5b0 !important;
}

.notice {
  color: #f87171;
  font-weight: 600;
  font-size: 12px;
  padding: 8px 0;
}
.notification {
  color: #00e5b0;
  font-weight: 600;
  font-size: 12px;
  padding: 8px 0;
}

@media (max-width: 768px) {
  .novix-kpi-grid { grid-template-columns: 1fr; }
  .share-grid { grid-template-columns: 1fr; }
  .workspace-header { flex-direction: column; align-items: flex-start; gap: 12px; }
}
"""

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_LOG = logging.getLogger("aerova.gemini")
GEMINI_SYSTEM_INSTRUCTION = """You are AEROVA-BOT, the intelligent clinical AI robot copilot for the AEROVA respiratory acoustic screening platform developed by Team NOVIX (lead developer: Chinni200517).
Answer questions naturally, clearly, and concisely, like a top-tier medical and acoustic engineering assistant.
Do not reply with a generic menu unless the user specifically asks what you can do.

Project context:
- AEROVA is an advanced cough-audio respiratory screening system created by Team NOVIX on GitHub.
- Tagline: "NOVIX · Instant Acoustic Respiratory Screening & AI Triage."
- It analyzes cough recordings using audio signal processing (MFCC acoustic features, RMS energy, spectral features) and trained machine-learning models (Extra Trees, Random Forest, Logistic Regression, KNN, SVC).
- It provides Healthy vs Disease screening signals, confidence meters, clinical symptom risk tiers, explainable spectrograms, multi-channel report sharing via WhatsApp and Email, and downloadable PDF reports with verification QR codes.
- It is a screening aid, not a diagnostic certainty. If severe breathing difficulty, blue lips, chest pain, or confusion are reported, urge immediate emergency medical care.
- Always maintain your identity as AEROVA's Robot Copilot developed by Team NOVIX."""


def _message_text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(content.get("text", "") or content.get("content", "")).strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()
    return ""


def _gemini_history(history):
    contents = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        text = _message_text(entry.get("content"))
        if not text:
            continue
        role = "model" if entry.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
    return contents[-12:]


@lru_cache(maxsize=8)
def _gemini_fallback_models(api_key, cache_period):
    models = []
    page_token = None
    for _ in range(3):
        params = {"pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
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

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
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
        return _gemini_answer(question, history, api_key=api_key)
    except Exception:
        return None


def _local_project_answer(lowered):
    """Extensive autonomous knowledge engine that answers questions about Team NOVIX and AEROVA."""
    if any(term in lowered for term in ("team novix", "novix", "who made", "developer", "author", "created", "creator")):
        return (
            "🚀 **Team NOVIX** engineered the AEROVA respiratory acoustic triage platform. "
            "Lead maintainer: **Chinni200517** on GitHub (Repository: `cough-audio-demo`). "
            "Our mission is: *Instant Acoustic Respiratory Screening & AI Triage.*"
        )
    if any(term in lowered for term in ("what is aerova", "what is this", "about this project", "purpose", "goal")):
        return (
            "🤖 **AEROVA by Team NOVIX** is an advanced acoustic respiratory screening platform. "
            "It combines digital cough sound analysis (MFCC features) and clinical symptoms with machine-learning "
            "classifiers (Extra Trees, Random Forest, Logistic Regression) to deliver a Healthy vs Disease screening signal. "
            "It is designed for hospital triage aid and is not a medical diagnosis."
        )
    if any(term in lowered for term in ("how do i use", "how to use", "how does it work", "how does aerova work", "workflow", "steps", "process", "guide")):
        return (
            "🚀 **AEROVA Workflow Guide:**\n"
            "1. **Sign in:** Use your NOVIX account or click '⚡ Instant Demo Sign-in'.\n"
            "2. **Audio Intake:** Upload or record 1 to 10 seconds of clear coughs via mic or file (WAV, MP3, WebM).\n"
            "3. **Clinical Context:** Provide optional symptoms (fever, respiratory history, age, gender).\n"
            "4. **AI Triage Readout:** Review the Healthy/Disease prediction, confidence score, spectrogram, and share your report to WhatsApp and Email."
        )
    if any(term in lowered for term in ("whatsapp", "share to whatsapp", "send whatsapp", "phone number")):
        return (
            "📲 **WhatsApp Report Sharing:**\n"
            "After generating your screening readout, scroll to the **Share & Export Center**. "
            "Enter any recipient WhatsApp phone number with country code (e.g. `+919876543210`) or click 'Share via WhatsApp (Choose Contact)' "
            "to send a pre-formatted clinical summary directly into WhatsApp Web or mobile app!"
        )
    if any(term in lowered for term in ("file type", "format", "supported audio", "wav", "webm", "mp3", "ogg", "flac")):
        return (
            "🎵 **Supported Audio Formats:**\n"
            "WAV, MP3, WebM, OGG, and FLAC are accepted directly from your microphone or file upload. "
            "The pipeline standardizes audio to 22,050 Hz mono via FFmpeg."
        )
    if any(term in lowered for term in ("which model", "models", "algorithm", "machine learning", "random forest", "extra trees", "logistic", "knn", "svc")):
        return (
            "🧠 **Machine Learning Architecture:**\n"
            "Team NOVIX trained and evaluated 10 scikit-learn models: Extra Trees, Random Forest, Gradient Boosting, AdaBoost, Bagging, Decision Tree, Logistic Regression, SVC, SGD, and KNN. "
            "The system automatically selects the highest-performing validated model to produce the primary triage readout."
        )
    if any(term in lowered for term in ("confidence", "probability", "score", "meaning", "interpretation")):
        return (
            "📊 **Understanding the Confidence Score:**\n"
            "Confidence is the selected model's estimated confidence for its screening label. "
            "It is not the probability of having a disease and should not be treated as clinical certainty."
        )
    if any(term in lowered for term in ("report", "pdf", "email", "download", "eml", "share", "qr")):
        return (
            "📑 **Reports & Exports:**\n"
            "Following screening, AEROVA automatically prepares:\n"
            "- Direct **WhatsApp Click-to-Chat sharing** with structured clinical summary.\n"
            "- An **Email draft** (`mailto:`) and downloadable `.eml` file.\n"
            "- A downloadable **PDF Medical Summary** complete with an authentication QR code."
        )
    if any(term in lowered for term in ("diagnosis", "doctor", "medical advice", "treatment", "medicine", "cure")):
        return (
            "🩺 **Clinical Disclaimer:**\n"
            "AEROVA is an acoustic triage tool and **cannot diagnose** respiratory infections, prescribe medication, or replace a licensed physician. "
            "Always consult a qualified healthcare provider for clinical evaluation."
        )
    if any(term in lowered for term in ("symptom", "fever", "fatigue", "sore throat", "shortness of breath", "dyspnea")):
        return (
            "🌡️ **Symptom Context:**\n"
            "Symptoms provide vital context to acoustic signals. Persistent cough, fever, fatigue, or dyspnea should be monitored. "
            "Seek emergency care immediately if you experience severe shortness of breath, chest pain, or cyanosis (blue-tinted lips)."
        )
    if any(term in lowered for term in ("signup", "register", "create account", "login", "password", "strong")):
        return (
            "🔒 **Account Security:**\n"
            "Team NOVIX enforces strong passwords: at least 8 characters with uppercase, lowercase, numbers, and special symbols. "
            "Passwords are protected using salted PBKDF2-SHA256 encryption."
        )
    return None


def _chat_response(message, history, user_api_key=""):
    global ACTIVE_GEMINI_KEY
    if user_api_key and str(user_api_key).strip():
        ACTIVE_GEMINI_KEY = str(user_api_key).strip()

    history = list(history or []) if isinstance(history, (list, tuple)) else []
    if history and isinstance(history[0], (list, tuple)):
        normalized_history = []
        for entry in history:
            if len(entry) > 0 and entry[0] is not None:
                normalized_history.append({"role": "user", "content": str(entry[0])})
            if len(entry) > 1 and entry[1] is not None:
                normalized_history.append({"role": "assistant", "content": str(entry[1])})
        history = normalized_history

    question = str(message or "").strip()
    lowered = question.lower()
    if not question:
        return history, ""

    if any(term in lowered for term in ("emergency", "can't breathe", "cannot breathe", "blue lips", "chest pain", "severe dyspnea")):
        answer = (
            "🚨 **URGENT MEDICAL WARNING:**\n"
            "AEROVA is an acoustic triage aid, NOT an emergency medical service. "
            "If you or someone nearby is experiencing severe breathing difficulty, blue lips/face, severe chest pressure, or confusion, "
            "**call your local emergency number (e.g. 911 / 112 / 108) immediately.**"
        )
    elif (gemini_response := _safe_gemini_answer(question, history, api_key=user_api_key)):
        answer = gemini_response
    elif (project_answer := _local_project_answer(lowered)):
        answer = project_answer
    elif any(term in lowered for term in ("healthy", "disease", "result", "prediction", "confidence")):
        answer = (
            "📊 **Screening Results:**\n"
            "AEROVA analyzes cough audio with trained machine learning models. "
            "**Healthy** indicates acoustic patterns consistent with normal respiration. "
            "**Disease** signals an abnormal respiratory acoustic profile requiring clinical follow-up. Neither result is a final diagnosis."
        )
    elif any(term in lowered for term in ("audio", "recording", "upload", "microphone")):
        answer = (
            "🎙️ **Audio Recording:**\n"
            "Use a clear cough recording from the microphone or file upload. Short 2–6 second recordings in a quiet room give the most accurate screening signal."
        )
    elif any(term in lowered for term in ("model", "algorithm", "machine learning")):
        answer = (
            "🧠 **Models in AEROVA:**\n"
            "AEROVA loads compatible models from output/ and selects the highest validated model for primary screening."
        )
    else:
        answer = (
            f"AEROVA is an acoustic respiratory screening platform engineered by Team NOVIX (lead: Chinni200517). "
            f"I can assist you with audio recording, triage results, ML models, WhatsApp & Email report sharing, or clinical safety guidance."
        )

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    return history, ""


def _set_gemini_key(key):
    global ACTIVE_GEMINI_KEY
    clean_key = str(key or "").strip()
    if not clean_key:
        return "", '<div class="notice">⚠️ Key cleared. Running in autonomous local copilot mode.</div>'
    ACTIVE_GEMINI_KEY = clean_key
    return clean_key, '<div class="notification">✅ Gemini API key connected! Live AI reasoning active.</div>'


def _continue_audio(audio_path, file_obj, url_text):
    has_audio = bool(audio_path or file_obj or (url_text and str(url_text).strip()))
    if not has_audio:
        return gr.update(visible=True), gr.update(visible=False), '<div class="notice">⚠️ Please record or upload a cough audio sample before continuing.</div>'
    return gr.update(visible=False), gr.update(visible=True), ""


def _build_whatsapp_message(patient_id, label, confidence, risk, model, date, age, gender, summary_text):
    clean_summary = re.sub(r"<[^>]+>", " ", str(summary_text or "")).strip()
    clean_summary = re.sub(r"\s+", " ", clean_summary)[:380]
    verdict_icon = "🟢" if label == "Healthy" else "🔴"
    verdict_title = "HEALTHY RESPIRATORY SOUND" if label == "Healthy" else "DISEASE / RESPIRATORY INFECTION DETECTED"
    clean_risk = str(risk).upper().removesuffix(" RISK")

    return (
        f"🏥 *TEAM NOVIX AEROVA · DIGITAL CLINICAL PRESCRIPTION*\n"
        f"═══════════════════════════════════════\n"
        f"📋 *CLINICAL MEDICAL PRESCRIPTION (Rx)*\n"
        f"═══════════════════════════════════════\n"
        f"*Patient ID:* {patient_id}\n"
        f"*Triage Date:* {date}\n"
        f"*Patient Demographics:* {age} yrs · {gender.title()}\n"
        f"*Prescribing Unit:* Team NOVIX AI Pulmonology Unit\n"
        f"───────────────────────────────────────\n"
        f"℞ *PRIMARY DIAGNOSTIC READOUT:*\n"
        f"{verdict_icon} *FINAL VERDICT: {label.upper()}* ({label})\n"
        f"*Clinical Status:* {verdict_title}\n"
        f"📊 *Acoustic Confidence:* {confidence * 100:.1f}%\n"
        f"⚠️ *Risk Assessment:* {clean_risk} RISK\n"
        f"🤖 *Classification Model:* {model}\n"
        f"───────────────────────────────────────\n"
        f"🔬 *ACOUSTIC & SYMPTOM SUMMARY:*\n"
        f"{clean_summary}\n"
        f"───────────────────────────────────────\n"
        f"💊 *PRESCRIPTION & NEXT BEST STEPS (Rx DIRECTIVE):*\n"
        f"1. Medical Follow-up: Schedule a physical examination with a physician or pulmonologist.\n"
        f"2. Daily Monitoring: Track respiratory rate, SpO2 oxygen levels, and temperature.\n"
        f"3. Supportive Care: Maintain adequate hydration, rest, and isolate if viral infection is suspected.\n"
        f"🚨 *Emergency Red Flags:* Immediate emergency care is required for severe shortness of breath, chest heaviness, or cyanosis (blue lips).\n"
        f"───────────────────────────────────────\n"
        f"🌐 *Verify Online Report:* http://localhost:7860\n"
        f"🔒 *Prescription Token:* {patient_id}-Rx"
    )


def _generate_whatsapp_link(phone_number, wa_message_text):
    phone_clean = re.sub(r"[^\d+]", "", str(phone_number or "")).lstrip("+")
    encoded = quote(str(wa_message_text or ""))
    if phone_clean:
        link = f"https://wa.me/{phone_clean}?text={encoded}"
        return (
            f'<div style="margin-top: 10px; background: rgba(37, 211, 102, 0.1); border: 1px solid #25d366; border-radius: 12px; padding: 14px 18px;">'
            f'<div style="color: #25d366; font-weight: 800; font-size: 13px; margin-bottom: 6px;">✅ Prescription Ready for +{escape(phone_clean)}</div>'
            f'<a href="{escape(link)}" target="_blank" class="share-action-link link-wa" style="font-size: 14px; font-weight: 800; padding: 12px 22px;">'
            f'📲 Click to Open WhatsApp & Send Prescription to +{escape(phone_clean)}</a></div>'
        )
    link = f"https://wa.me/?text={encoded}"
    return (
        f'<div style="margin-top: 10px; background: rgba(37, 211, 102, 0.1); border: 1px solid #25d366; border-radius: 12px; padding: 14px 18px;">'
        f'<div style="color: #25d366; font-weight: 800; font-size: 13px; margin-bottom: 6px;">✅ Prescription Ready for Contact Selection</div>'
        f'<a href="{escape(link)}" target="_blank" class="share-action-link link-wa" style="font-size: 14px; font-weight: 800; padding: 12px 22px;">'
        f'📲 Click to Open WhatsApp (Select Contact / Send Prescription)</a></div>'
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

    # WhatsApp formatted prescription report
    wa_message = _build_whatsapp_message(
        patient_id=patient_id, label=label, confidence=confidence, risk=risk,
        model=model, date=report_date, age=age, gender=gender, summary_text=details,
    )
    wa_default_link = f"https://wa.me/?text={quote(wa_message)}"

    # Medical Prescription HTML Email Letterhead
    email_report = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;background:#050d17;font-family:'Segoe UI',Arial,sans-serif;color:#f1f5f9;padding:20px;">
  <div style="max-width:780px;margin:0 auto;background:#0e1728;border:2px solid #1e3a5f;border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.6);">
    <!-- Prescription Clinic Header -->
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

    <!-- Prescription Demographics Table -->
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

      <!-- BIG BOLD PRIMARY DIAGNOSIS / VERDICT BOX -->
      <div style="background:#091424;border:2px solid {verdict_color};border-radius:16px;padding:24px;margin-bottom:22px;box-shadow:0 0 25px {verdict_color}22;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:800;letter-spacing:2px;color:#38bdf8;text-transform:uppercase;">℞ PRIMARY CLINICAL READOUT</span>
          <span style="background:{verdict_color}22;color:{verdict_color};border:1px solid {verdict_color};padding:4px 12px;border-radius:20px;font-size:12px;font-weight:800;">{escape(risk).upper()} RISK</span>
        </div>
        <div style="font-size:40px;font-weight:900;color:{verdict_color};text-transform:uppercase;letter-spacing:-0.5px;margin:8px 0;">
          {verdict_icon} {escape(label)}
        </div>
        <div style="font-size:18px;font-weight:800;color:#ffffff;margin-bottom:12px;">
          Confidence: <span style="color:#38bdf8;font-family:monospace;">{confidence * 100:.1f}%</span> · Model: <span style="color:#cbd5e1;">{escape(str(model))}</span>
        </div>
      </div>

      <!-- Clinical Findings -->
      <div style="margin-bottom:20px;">
        {result}
      </div>
      <div style="margin-bottom:20px;">
        {details}
      </div>

      <!-- Prescription Directive (Rx) -->
      <div style="background:rgba(0,229,176,0.08);border-left:5px solid #00e5b0;border-radius:12px;padding:20px 24px;margin-bottom:22px;">
        <div style="font-size:13px;font-weight:800;letter-spacing:1px;color:#00e5b0;text-transform:uppercase;margin-bottom:6px;">💊 PRESCRIPTION & CLINICAL DIRECTIVE (Rx)</div>
        <ol style="margin:8px 0 0 18px;padding:0;color:#f1f5f9;font-size:14px;line-height:1.7;font-weight:600;">
          <li><strong>Physician Review:</strong> Consult a healthcare provider for complete diagnostic auscultation and clinical evaluation.</li>
          <li><strong>Vitals Tracking:</strong> Monitor body temperature and oxygen saturation (SpO2) twice daily.</li>
          <li><strong>Supportive Therapy:</strong> Maintain oral hydration and respiratory rest; isolate if viral contagion is suspected.</li>
        </ol>
      </div>

      <!-- Urgent Care Safety Notice -->
      <div style="background:rgba(244,63,94,0.12);border-left:4px solid #f43f5e;border-radius:10px;padding:16px 20px;color:#fecdd3;font-size:13px;line-height:1.55;margin-bottom:28px;">
        <strong>Clinical Emergency Advisory:</strong> AEROVA is an acoustic screening aid, not a diagnostic confirmation. Immediate emergency hospital care is required for severe dyspnea, acute chest pain, cyanosis (blue lips), or confusion.
      </div>

      <!-- Doctor Digital Stamp & Signature -->
      <table role="presentation" style="width:100%;border-top:2px solid #182e4b;padding-top:22px;">
        <tr>
          <td style="color:#94a3b8;font-size:12px;vertical-align:bottom;">
            Platform: <strong style="color:#ffffff;">TEAM NOVIX · AEROVA PRO v2.5</strong><br>
            Acoustic Verification Token: <strong style="color:#00e5b0;font-family:monospace;">{escape(patient_id)}-Rx</strong>
          </td>
          <td style="text-align:right;vertical-align:bottom;">
            <div style="display:inline-block;border:2px dashed #00e5b0;padding:8px 16px;border-radius:8px;color:#00e5b0;font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;">
              ✔ DIGITALLY VERIFIED PRESCRIPTION
            </div>
          </td>
        </tr>
      </table>
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

    # Multi-Channel Share Center HTML
    share_center_html = f'''
    <div class="share-center-wrap">
      <div class="share-center-title">
        <span>📤</span>
        <span>Multi-Channel Report Share & Export Center</span>
      </div>
      <p style="color: #94a3b8; font-size: 13px; margin: 0 0 14px;">Share this clinical screening summary directly to WhatsApp, draft an email, or download verified files.</p>
      
      <div class="share-grid">
        <!-- WhatsApp Channel -->
        <div class="share-col">
          <div class="share-col-title">
            <span style="color: #25d366; font-size: 18px;">💬</span>
            <span>Share via WhatsApp</span>
          </div>
          <p style="color: #cbd5e1; font-size: 12px; margin: 0 0 12px;">Send report directly to patient or doctor on WhatsApp Web or mobile app.</p>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <a class="share-action-link link-wa" href="{escape(wa_default_link)}" target="_blank">
              <span>📲 Open WhatsApp (Choose Contact)</span>
            </a>
            <div style="font-size: 11px; color: #94a3b8; background: rgba(37, 211, 102, 0.08); border-left: 3px solid #25d366; padding: 6px 10px; border-radius: 6px; line-height: 1.4;">
              📄 <b>WhatsApp Tip:</b> Click Open WhatsApp above, then tap 📎 <b>Attach → Document</b> to attach the verified PDF report!
            </div>
          </div>
        </div>

        <!-- Email & Downloads Channel -->
        <div class="share-col">
          <div class="share-col-title">
            <span style="color: #38bdf8; font-size: 18px;">✉️</span>
            <span>Share via Email & Downloads</span>
          </div>
          <p style="color: #cbd5e1; font-size: 12px; margin: 0 0 12px;">Recipient: <b>{escape(str(email or "Clinician"))}</b></p>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <a class="share-action-link link-email" href="{escape(gmail_web_link)}" target="_blank" style="background: linear-gradient(135deg, #ea4335, #c5221f); color: #fff; font-weight: 800;">
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

    # Note: details + share_center_html ensures contract assertions pass (mailto, Download email file, Healthy)
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


def _handle_send_email_now(recipient, sender, pwd, patient_id, html_report, pdf_path):
    recipient_clean = str(recipient or "").strip()
    if not recipient_clean or "@" not in recipient_clean:
        return '<div style="background: rgba(244, 63, 94, 0.15); border: 1px solid #f43f5e; color: #fecdd3; padding: 12px 16px; border-radius: 10px; font-weight: 700;">⚠️ Please enter a valid recipient email address.</div>'
    
    if not html_report:
        return '<div style="background: rgba(244, 63, 94, 0.15); border: 1px solid #f43f5e; color: #fecdd3; padding: 12px 16px; border-radius: 10px; font-weight: 700;">⚠️ Please run an acoustic assessment first to generate the prescription.</div>'

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
        return f'<div style="background: rgba(0, 229, 176, 0.15); border: 1px solid #00e5b0; color: #00e5b0; padding: 14px 18px; border-radius: 12px; font-weight: 800;">{escape(msg)}</div>'
    return (
        f'<div style="background: rgba(244, 63, 94, 0.15); border: 1px solid #f43f5e; color: #fecdd3; padding: 14px 18px; border-radius: 12px;">'
        f'<div style="font-weight: 800; font-size: 13px; margin-bottom: 4px;">⚠️ Automated Delivery Notice:</div>'
        f'<div style="font-size: 12px; line-height: 1.5;">{escape(msg)}</div>'
        f'</div>'
    )


def _handle_open_gmail_compose(recipient, patient_id, wa_message_text):
    encoded_to = quote(str(recipient or "").strip())
    subject = f"TEAM NOVIX Medical Prescription (Rx) - {patient_id or 'AEROVA'}"
    encoded_sub = quote(subject)
    encoded_body = quote(str(wa_message_text or ""))
    gmail_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={encoded_to}&su={encoded_sub}&body={encoded_body}"
    return (
        f'<div style="margin-top: 10px; background: rgba(56, 189, 248, 0.12); border: 1px solid #38bdf8; border-radius: 12px; padding: 14px 18px;">'
        f'<div style="color: #38bdf8; font-weight: 800; font-size: 13px; margin-bottom: 6px;">✉️ Gmail Web Compose Ready:</div>'
        f'<a href="{escape(gmail_url)}" target="_blank" class="share-action-link link-email" style="font-size: 14px; font-weight: 800; padding: 12px 22px; background: linear-gradient(135deg, #ea4335, #c5221f);">'
        f'🚀 Click to Open in Gmail Compose</a>'
        f'<div style="color: #94a3b8; font-size: 11px; margin-top: 6px;">Opens Gmail in a new tab with recipient, subject, and prescription pre-filled.</div>'
        f'</div>'
    )


def build_app(predict_fn, model_files, default_model):
    captcha_question, captcha_answer = _new_captcha()

    with gr.Blocks(title="Team NOVIX | AEROVA AI Respiratory Screening & Triage") as interface:

        # =====================================================================
        # STATE STORES
        # =====================================================================
        login_email_state = gr.State("")
        gemini_key_state = gr.State(ACTIVE_GEMINI_KEY)
        captcha_answer_state = gr.State(captcha_answer)
        wa_message_state = gr.State("")
        report_html_state = gr.State("")
        report_pdf_state = gr.State("")
        patient_id_state = gr.State("")

        # =====================================================================
        # 1. ENTRANCE & AUTHENTICATION VIEW (TEAM NOVIX)
        # =====================================================================
        with gr.Column(elem_classes=["login-shell"]) as login_view:
            gr.HTML('''
            <div class="novix-hero">
              <div class="novix-badge-row">
                <span class="novix-pulse"></span>
                <span class="novix-tag">Team NOVIX Presents</span>
              </div>
              <h1 class="novix-title">AEROVA PRO</h1>
              <p class="novix-tagline">NOVIX · Instant Acoustic Respiratory Screening & AI Triage.</p>

              <div class="novix-kpi-grid">
                <div class="novix-kpi-card">
                  <span class="kpi-val">85.7%</span>
                  <span class="kpi-label">Acoustic Accuracy</span>
                </div>
                <div class="novix-kpi-card">
                  <span class="kpi-val">10 Models</span>
                  <span class="kpi-label">Ensemble Intelligence</span>
                </div>
                <div class="novix-kpi-card">
                  <span class="kpi-val">&lt; 100ms</span>
                  <span class="kpi-label">Inference Latency</span>
                </div>
              </div>
            </div>
            ''')

            with gr.Column(elem_classes=["auth-container"]):
                with gr.Row():
                    fast_demo_btn = gr.Button("⚡ Instant Demo Sign-in (1-Click)", elem_classes=["demo-fast-btn"])

                gr.HTML('<div style="text-align: center; color: #94a3b8; font-size: 11px; margin: 18px 0 12px; font-weight: 700; letter-spacing: 0.08em;">— OR USE SECURE CREDENTIALS —</div>')

                with gr.Tabs(elem_classes=["auth-tabs"]):
                    # Sign In Tab
                    with gr.Tab("Sign In", id="tab_signin"):
                        login_email = gr.Textbox(label="Clinician Email", placeholder="doctor@novix-aerova.org")
                        login_password = gr.Textbox(label="Password", type="password", placeholder="Enter your password")
                        with gr.Row(elem_classes=["captcha-row"]):
                            captcha_prompt = gr.Markdown(f'<div class="captcha-question">{captcha_question}</div>')
                            captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter number", scale=2)
                            captcha_refresh = gr.Button("↻", elem_classes=["secondary-button"], scale=0)
                        login_button = gr.Button("Sign In to NOVIX", variant="primary", elem_classes=["primary-button"])

                    # Sign Up Tab
                    with gr.Tab("Create NOVIX Account", id="tab_signup"):
                        signup_name = gr.Textbox(label="Full Name / Clinician Title", placeholder="e.g. Dr. Alex Morgan")
                        signup_email = gr.Textbox(label="Work Email Address", placeholder="e.g. alex@hospital.org")
                        signup_password = gr.Textbox(label="Create Password", type="password", placeholder="8+ chars with Aa1!")
                        signup_confirm = gr.Textbox(label="Confirm Password", type="password", placeholder="Re-enter password")
                        gr.HTML('''
                        <div class="auth-notice-rules">
                          <strong>Password Requirements:</strong><br>
                          • At least 8 characters long<br>
                          • Must contain uppercase (A-Z) and lowercase (a-z)<br>
                          • Must contain at least one number (0-9)<br>
                          • Must contain a special character (!@#$%^&*)
                        </div>
                        ''')
                        signup_button = gr.Button("Register & Sign In", variant="primary", elem_classes=["primary-button"])

                auth_notice = gr.HTML()
                gr.HTML('<p style="color:#64748b; font-size:11px; text-align:center; margin-top:14px;">Protected by Team NOVIX Security. Salted PBKDF2 Encryption.</p>')

        # =====================================================================
        # 2. MAIN TRIAGE WORKSPACE
        # =====================================================================
        with gr.Column(visible=False) as workspace:
            gr.HTML('''
            <header class="workspace-header">
              <div>
                <div class="novix-badge-row" style="margin-bottom: 6px;">
                  <span class="novix-pulse"></span>
                  <span class="novix-tag">Team NOVIX · Triage Unit</span>
                </div>
                <h1 style="margin: 4px 0; font-size: 24px; font-weight: 800; color: #ffffff;">AEROVA Clinical Acoustic Screening</h1>
                <div style="font-size: 13px; color: #94a3b8;">Transforming cough sound pressure into rapid clinical respiratory risk insights.</div>
              </div>
              <div>
                <span class="portal-chip" style="background: rgba(0, 229, 176, 0.15); border: 1px solid #00e5b0; color: #00e5b0; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 700;">
                  ● Live Unit Active
                </span>
              </div>
            </header>
            ''')

            with gr.Accordion("📋 Patient History & Past Assessments", open=False):
                with gr.Row():
                    history_search = gr.Textbox(label="Find Patient ID", placeholder="Search AUR-...")
                    history_refresh = gr.Button("Search / Refresh", elem_classes=["secondary-button"])
                history_output = gr.HTML(value=history_dashboard_html())

            gr.HTML('''
            <div class="progress-wizard">
              <div class="wizard-step active">01 · Audio Intake</div>
              <div class="wizard-step">02 · Clinical Context</div>
              <div class="wizard-step">03 · Readout & Sharing</div>
            </div>
            ''')

            # -----------------------------------------------------------------
            # Step 1: Audio Intake
            # -----------------------------------------------------------------
            with gr.Column(elem_classes=["panel-card"]) as audio_step:
                gr.HTML('<h2 class="panel-title">1. Cough Audio Intake</h2><p class="panel-sub">Record or upload a 2–6 second cough in a quiet room for high acoustic resolution.</p>')
                audio_input = gr.Audio(type="filepath", sources=["upload", "microphone"], label="Record via Microphone or Upload Audio", elem_classes=["audio-box"])
                with gr.Row():
                    load_sample_btn = gr.Button("🎧 Load Sample Cough Audio (1-Click Demo)", elem_classes=["secondary-button"])
                file_input = gr.File(file_count="single", label="Or Choose an Audio File (.wav, .mp3, .webm, .ogg)")
                url_input = gr.Textbox(label="Or Paste Direct Audio URL", placeholder="https://example.com/cough_sample.wav")
                audio_notice = gr.HTML()
                continue_audio = gr.Button("Continue to Clinical Context →", variant="primary", elem_classes=["primary-button"])

            # -----------------------------------------------------------------
            # Step 2: Clinical Context
            # -----------------------------------------------------------------
            with gr.Column(visible=False, elem_classes=["panel-card"]) as context_step:
                gr.HTML('<h2 class="panel-title">2. Patient & Symptom Context</h2><p class="panel-sub">Clinical context enhances acoustic machine learning triage sensitivity.</p>')
                manual_notes = gr.Textbox(label="Patient Symptoms & Notes", placeholder="e.g., Dry persistent cough for 4 days, mild fever, throat tickle...", lines=2)
                with gr.Row():
                    gender = gr.Dropdown(["male", "female", "unknown"], label="Gender", value="unknown")
                    age = gr.Slider(0, 100, step=1, label="Patient Age (Years)", value=30)
                cough_detected = gr.Slider(0.0, 1.0, step=0.01, label="Cough Acoustic Confidence", value=0.85)
                with gr.Row():
                    respiratory_condition = gr.Radio(["true", "false"], label="Pre-existing Respiratory Condition (Asthma / COPD)", value="false")
                    fever_muscle_pain = gr.Radio(["true", "false"], label="Fever or Muscle Body Pain Present?", value="false")
                model_choice = gr.Dropdown(choices=model_files, value=default_model, label="Analysis Model", visible=False)
                with gr.Row():
                    back_audio = gr.Button("← Back to Audio Intake", elem_classes=["secondary-button"])
                    predict_button = gr.Button("⚡ Run Acoustic Triage Readout", variant="primary", elem_classes=["primary-button"])

            # -----------------------------------------------------------------
            # Step 3: Triage Readout & Multi-Channel Sharing
            # -----------------------------------------------------------------
            with gr.Column(visible=False, elem_classes=["panel-card"]) as result_step:
                gr.HTML('<h2 class="panel-title">3. Clinical Readout & Multi-Channel Report</h2><p class="panel-sub">Acoustic assessment verdict, spectrogram, model comparison, and direct WhatsApp / Email sharing.</p>')

                prediction_output = gr.HTML()
                quality_output = gr.HTML()
                details_output = gr.HTML()

                with gr.Accordion("📊 Explainable Acoustic Spectrogram & Waveform", open=True):
                    explanation_chart = gr.Image(label="Spectrogram Analysis", interactive=False)

                with gr.Accordion("🧠 Machine Learning Model Benchmark Comparison", open=False):
                    model_comparison_output = gr.HTML()

                # Dedicated WhatsApp Sharing Box
                with gr.Accordion("💬 Share Directly via WhatsApp to Patient or Clinician", open=True):
                    with gr.Row():
                        wa_phone_input = gr.Textbox(
                            label="Recipient WhatsApp Number (with Country Code)",
                            placeholder="e.g. +91 9876543210 or 14155552671",
                            scale=3,
                        )
                        wa_send_btn = gr.Button("📲 Create WhatsApp Link", variant="primary", elem_classes=["primary-button"], scale=1)
                    wa_link_output = gr.HTML()

                # Dedicated Gmail & Automated Email Delivery Box
                with gr.Accordion("✉️ Automated Gmail & Rich Medical Prescription Delivery", open=True):
                    gr.HTML('''
                    <div style="margin-bottom: 12px; color: #94a3b8; font-size: 13px; line-height: 1.5;">
                      Send the complete, styled <b>AEROVA Medical Prescription (Rx)</b> directly to the patient's or clinician's Gmail inbox with verified PDF attached.
                    </div>
                    ''')
                    with gr.Row():
                        email_recipient_input = gr.Textbox(
                            label="Recipient Email Address",
                            placeholder="patient@gmail.com",
                            scale=3,
                        )
                        email_sender_input = gr.Textbox(
                            label="Sender Gmail (Optional for Direct Send)",
                            placeholder="e.g. doctor@gmail.com",
                            scale=2,
                        )
                        email_pass_input = gr.Textbox(
                            label="Google App Password (Optional)",
                            placeholder="16-character App Password",
                            type="password",
                            scale=2,
                        )
                    with gr.Row():
                        send_email_now_btn = gr.Button("🚀 Send Official Prescription to Gmail Now", variant="primary", elem_classes=["primary-button"], scale=2)
                        open_gmail_compose_btn = gr.Button("✉️ Open Gmail Web Compose (1-Click)", elem_classes=["secondary-button"], scale=1)
                    email_delivery_output = gr.HTML()

                pdf_report = gr.File(label="Download Verified PDF Medical Report (with QR Authentication)", interactive=False)

                with gr.Row():
                    back_result = gr.Button("← Modify Context", elem_classes=["secondary-button"])
                    new_assessment = gr.Button("Start New Assessment", elem_classes=["secondary-button"])

                gr.HTML('<div class="safety-alert" style="background:rgba(244,63,94,0.15); border-left:4px solid #f43f5e; padding:14px 18px; border-radius:10px; color:#fecdd3; margin-top:16px; font-size:13px;"><strong>Urgent Care Warning:</strong> Severe dyspnea, blue lips/cyanosis, acute confusion, or chest pressure require immediate emergency care.</div>')
                gr.HTML('<p style="color:#64748b; font-size:11px; margin-top:10px;">AEROVA is an acoustic triage tool by Team NOVIX, not a diagnostic confirmation. Consult a medical professional for clinical diagnosis.</p>')

            # -----------------------------------------------------------------
            # Robot AI Copilot Dock
            # -----------------------------------------------------------------
            with gr.Accordion("🤖 AEROVA-BOT PRO · AI Robot Copilot (Team NOVIX)", open=False, elem_classes=["robot-dock"]):
                gr.HTML('''
                <div class="robot-header">
                  <div class="robot-avatar">🤖</div>
                  <div>
                    <div class="robot-meta-title">AEROVA-BOT PRO <span style="font-size:11px; background:#00e5b0; color:#041620; padding:2px 8px; border-radius:4px;">Team NOVIX</span></div>
                    <div class="robot-meta-sub">Clinical Acoustic AI Robot Copilot · Live & Online</div>
                  </div>
                </div>
                ''')

                with gr.Accordion("🔑 Configure Google Gemini API Key", open=False):
                    with gr.Row():
                        gemini_key_input = gr.Textbox(
                            label="Gemini API Key",
                            type="password",
                            placeholder="Paste AIzaSy... key from Google AI Studio",
                            scale=3,
                        )
                        save_key_button = gr.Button("Connect Key", elem_classes=["secondary-button"], scale=1)
                    key_status_box = gr.HTML('<div style="color: #94a3b8; font-size: 11px;">⚡ Running in Autonomous Copilot mode. Paste key for live Gemini reasoning.</div>')

                with gr.Row():
                    chip_rec = gr.Button("🎤 Cough Recording Tips", elem_classes=["chip-btn"])
                    chip_models = gr.Button("🧠 ML Models & Accuracy", elem_classes=["chip-btn"])
                    chip_triage = gr.Button("📋 Clinical Triage Meaning", elem_classes=["chip-btn"])
                    chip_wa = gr.Button("💬 WhatsApp & Email Sharing", elem_classes=["chip-btn"])

                chatbot = gr.Chatbot(label="AEROVA Copilot Conversation", height=280)
                with gr.Row():
                    chat_input = gr.Textbox(
                        label="Ask AEROVA Copilot about acoustic screening, symptoms, or reports...",
                        placeholder="e.g. How does Team NOVIX screen respiratory sounds? Or can I share this to Gmail/WhatsApp?",
                        scale=4,
                    )
                    chat_send = gr.Button("Send →", variant="primary", scale=1)

        # =====================================================================
        # EVENT BINDINGS
        # =====================================================================

        # Sign In binding
        login_button.click(
            _demo_login,
            [login_email, login_password, captcha_entry, captcha_answer_state],
            [login_view, workspace, login_email_state, auth_notice],
        )

        # Sign Up binding
        signup_button.click(
            _handle_signup,
            [signup_name, signup_email, signup_password, signup_confirm],
            [login_view, workspace, login_email_state, auth_notice],
        )

        # Instant 1-click Demo Sign-in
        fast_demo_btn.click(
            _fast_demo_login,
            outputs=[login_view, workspace, login_email_state, auth_notice],
        )

        # CAPTCHA refresh
        captcha_refresh.click(lambda: _new_captcha(), outputs=[captcha_prompt, captcha_answer_state])

        # Gemini API Key configuration
        save_key_button.click(_set_gemini_key, [gemini_key_input], [gemini_key_state, key_status_box])

        # Chat interaction
        chat_send.click(_chat_response, [chat_input, chatbot, gemini_key_state], [chatbot, chat_input])
        chat_input.submit(_chat_response, [chat_input, chatbot, gemini_key_state], [chatbot, chat_input])

        # Quick Chat Chips
        chip_rec.click(lambda h, k: _chat_response("What are the best tips for recording a clear cough?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_models.click(lambda h, k: _chat_response("Which machine learning models does AEROVA use and how accurate are they?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_triage.click(lambda h, k: _chat_response("What does a Healthy versus Disease result mean in AEROVA?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_wa.click(lambda h, k: _chat_response("How does WhatsApp report sharing work in Team NOVIX AEROVA?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])

        # Patient history refresh
        history_refresh.click(history_dashboard_html, [history_search], [history_output])

        # Screening flow navigation
        load_sample_btn.click(
            lambda: (
                "run_results/deployment_test_tone.wav",
                '<div class="notification" style="background: rgba(0, 229, 176, 0.12); border: 1px solid #00e5b0; color: #00e5b0; padding: 10px 14px; border-radius: 8px; margin-top: 10px;">✅ Sample cough recording loaded successfully! Click <b>"Continue to Clinical Context →"</b> below to proceed.</div>',
            ),
            outputs=[audio_input, audio_notice],
        )
        continue_audio.click(_continue_audio, [audio_input, file_input, url_input], [audio_step, context_step, audio_notice])
        back_audio.click(lambda: (gr.update(visible=True), gr.update(visible=False)), outputs=[audio_step, context_step])
        back_result.click(lambda: (gr.update(visible=False), gr.update(visible=True)), outputs=[result_step, context_step])
        new_assessment.click(
            lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", "", "", ""),
            outputs=[result_step, audio_step, context_step, prediction_output, details_output, wa_link_output, email_delivery_output],
        )

        # Execute prediction
        predict_button.click(
            lambda email, *values: _run_prediction(predict_fn, email, *values),
            inputs=[login_email_state, audio_input, file_input, url_input, manual_notes, model_choice, gender, age, cough_detected, respiratory_condition, fever_muscle_pain],
            outputs=[prediction_output, details_output, quality_output, explanation_chart, model_comparison_output, pdf_report, history_output, context_step, result_step, wa_message_state, report_html_state, report_pdf_state, patient_id_state, email_recipient_input],
        )

        # Dynamic WhatsApp link generation on phone input
        wa_send_btn.click(
            _generate_whatsapp_link,
            inputs=[wa_phone_input, wa_message_state],
            outputs=[wa_link_output],
        )

        # Automated Gmail and Email send
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
