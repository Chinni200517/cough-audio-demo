from html import escape
from datetime import datetime
import os
import re
import secrets
from urllib.parse import quote

import gradio as gr
import requests

from reporting import create_pdf_report, history_dashboard_html, save_assessment


def _new_captcha():
  first = secrets.randbelow(8) + 2
  second = secrets.randbelow(8) + 2
  return f"What is {first} + {second}?", str(first + second)


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_SYSTEM_INSTRUCTION = """You are the AEROVA respiratory-screening assistant.
Answer the user's question clearly and helpfully. AEROVA analyses cough audio as a
screening aid; it cannot diagnose, rule out, or prescribe treatment for a medical
condition. Do not invent test results or medical facts. Encourage professional care
for concerning symptoms. If the user reports severe breathing difficulty, blue lips,
confusion, severe chest pain, or rapidly worsening symptoms, tell them to call their
local emergency number now. Keep answers concise and use plain language."""


def _message_text(content):
  if isinstance(content, str):
    return content.strip()
  if isinstance(content, list):
    return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text").strip()
  return ""


def _gemini_history(history):
  contents = []
  for entry in history:
    if not isinstance(entry, dict):
      continue
    text = _message_text(entry.get("content"))
    if text:
      role = "model" if entry.get("role") == "assistant" else "user"
      contents.append({"role": role, "parts": [{"text": text}]})
  return contents[-12:]


def _gemini_answer(question, history):
  api_key = os.environ.get("GEMINI_API_KEY", "").strip()
  if not api_key:
    return None
  model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
  payload = {
    "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_INSTRUCTION}]},
    "contents": _gemini_history(history) + [{"role": "user", "parts": [{"text": question}]}],
    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
  }
  try:
    response = requests.post(GEMINI_API_URL.format(model=model), headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, json=payload, timeout=25)
    response.raise_for_status()
    parts = response.json()["candidates"][0]["content"]["parts"]
    answer = "\n".join(str(part.get("text", "")) for part in parts).strip()
    return answer or None
  except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
    return None


def _chat_response(message, history):
  history = list(history or [])
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
  if any(term in lowered for term in ("emergency", "can't breathe", "cannot breathe", "blue lips", "chest pain")):
    answer = "AEROVA is a screening aid, not emergency care. For severe breathing difficulty, blue lips, confusion, or severe chest pain, call your local emergency number now."
  elif (gemini_response := _gemini_answer(question, history)):
    answer = gemini_response
  elif any(term in lowered for term in ("healthy", "disease", "result", "prediction", "confidence")):
    answer = "AEROVA analyses cough audio with trained classification models and combines the sound signal with symptoms. Healthy means no obvious abnormal pattern was detected; Disease means an abnormal respiratory signal was detected. Neither result is a diagnosis."
  elif any(term in lowered for term in ("audio", "recording", "upload", "microphone")):
    answer = "Use a clear cough recording from the upload or microphone control. A short recording with low background noise gives AEROVA a better signal; the quality check flags silence, clipping, and very short recordings."
  elif any(term in lowered for term in ("model", "algorithm", "machine learning")):
    answer = "AEROVA loads compatible trained models, selects the strongest validated model, and shows model comparison with confidence and validation accuracy."
  elif any(term in lowered for term in ("privacy", "data", "history", "report")):
    answer = "AEROVA creates a patient ID, screening summary, optional PDF, and local assessment history for this demo. Do not enter unnecessary personal information, and treat reports as screening aids."
  else:
    answer = "I can explain AEROVA's audio workflow, Healthy versus Disease results, model confidence, recording quality, reports, privacy, or urgent-care guidance."
  history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
  return history, ""


APP_CSS = """
:root {
  --bg: #061c2d;
  --bg-strong: #0b2d42;
  --panel: rgba(16, 35, 49, 0.9);
  --panel-soft: rgba(20, 51, 67, 0.82);
  --ink: #eaf7ff;
  --muted: #9eb8c9;
  --primary: #20b7a5;
  --primary-deep: #087f78;
  --secondary: #a9f0d5;
  --accent: #f17c55;
  --success: #1a9b68;
  --warning: #bd7810;
  --line: rgba(148, 196, 220, 0.25);
  --shadow: 0 22px 50px rgba(5, 17, 29, 0.45);
}

body, .gradio-container {
  background: radial-gradient(circle at top left, #0d334d 0%, #071d2d 38%, #050f18 100%) !important;
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
  padding: 8px 12px;
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
  padding: 22px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(2px);
}

.panel-title {
  font-size: 26px;
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
  font: 700 26px/1 Arial, sans-serif;
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
}

.primary-button:hover {
  filter: brightness(1.03);
}

.secondary-button {
  border: 1px solid #cfe0eb !important;
  color: var(--primary-deep) !important;
  border-radius: 12px !important;
  background: #f4fbff !important;
}

.result-card, .details-panel {
  border-radius: 20px;
  padding: 23px;
  background: linear-gradient(180deg, #ffffff 0%, #f7fbfd 100%);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  color: #123048;
}

.result-card {
  border-top: 6px solid var(--primary);
}

.result-card .result-kicker,
.details-panel .section-label {
  color: #1b5f7b;
}

.result-card .result-summary,
.result-card .result-meta,
.result-card .detail-section p,
.details-panel .detail-section p,
.details-panel .recommendation p,
.result-card .result-error span {
  color: #214d63;
}

.status-review {
  border-top-color: var(--accent);
}

.result-error {
  border-top-color: #bd4e4e;
  display: grid;
  gap: 6px;
}

.result-error span {
  color: var(--muted);
  font: 13px Arial, sans-serif;
}

.result-kicker {
  margin-bottom: 12px;
  color: var(--primary);
}

.result-heading {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 14px;
  font-size: 38px;
  font-weight: 700;
  color: var(--ink);
}

.confidence {
  color: var(--primary);
  font: 700 13px Arial, sans-serif;
  white-space: nowrap;
}

.result-summary {
  font: 17px/1.5 Arial, sans-serif;
  color: var(--muted);
  margin: 10px 0 18px;
}

.meter {
  height: 10px;
  background: #e8f0f4;
  border-radius: 999px;
  overflow: hidden;
}

.meter span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--secondary) 0%, var(--primary) 100%);
  border-radius: inherit;
}

.result-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 15px;
  color: var(--muted);
  font: 12px Arial, sans-serif;
}

.risk-pill, .symptom-chip {
  display: inline-block;
  border-radius: 999px;
  padding: 7px 12px;
  font: 700 11px Arial, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.risk-low { background: #c8f2dc; color: #075b3d; border: 1px solid #63c893; }
.risk-medium { background: #ffedbd; color: #714500; border: 1px solid #e0ae45; }
.risk-high { background: #ffd7d1; color: #8a2118; border: 1px solid #e87969; }

.details-panel {
  margin-top: 14px;
}

.detail-section {
  padding: 0 0 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid #edf2f5;
}

.detail-section p, .recommendation p {
  font: 15px/1.55 Arial, sans-serif;
  margin: 7px 0 0;
  color: var(--muted);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.symptom-chip {
  background: #e9f7f7;
  color: var(--primary-deep);
  text-transform: none;
  letter-spacing: 0;
}

.recommendation {
  background: linear-gradient(135deg, #f7fbf8 0%, #f3fbff 100%);
  border-left: 4px solid var(--accent);
  padding: 15px 16px;
  border-radius: 14px;
}

.footnote {
  color: var(--muted);
  font: 12px/1.5 Arial, sans-serif;
  padding: 16px 2px 0;
}

.login-shell {
  max-width: 920px;
  margin: 58px auto 20px;
}

.login-panel {
  background: linear-gradient(135deg, rgba(14,30,41,0.96), rgba(18,48,62,0.96));
  border: 1px solid var(--line);
  border-radius: 28px;
  box-shadow: var(--shadow);
  padding: 28px;
}

.login-mark {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font: 700 26px Georgia, serif;
  color: white;
}

.login-mark::before {
  content: "";
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: linear-gradient(135deg, #9ce0d6, #53b4c8);
  display: inline-block;
  box-shadow: inset 0 0 8px rgba(255,255,255,.8);
}

.login-copy {
  color: var(--muted);
  font: 14px/1.6 Arial, sans-serif;
  margin: 14px 0 24px;
}

.login-panel label span, .login-panel .gr-input-label {
  color: white !important;
}

.login-note {
  color: #bfd5e8;
  font: 12px/1.5 Arial, sans-serif;
  text-align: center;
  margin-top: 14px;
}

.progress {
  display: flex;
  gap: 10px;
  margin: 22px 0 18px;
}

.progress-item {
  flex: 1;
  border-top: 4px solid #dfeaf1;
  padding-top: 10px;
  color: var(--muted);
  font: 700 10px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.progress-item.active {
  color: var(--primary);
  border-color: var(--primary);
}

.progress-item.done {
  color: var(--success);
  border-color: #95d3bf;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}

.result-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.notice {
  color: #a64a42;
  font: 13px Arial, sans-serif;
  padding: 10px 0;
}

.share-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.share-action {
  display: inline-block;
  padding: 10px 13px;
  border: 1px solid #cfe1ec;
  border-radius: 10px;
  color: var(--primary-deep) !important;
  background: #f4fbff;
  font: 700 12px Arial, sans-serif;
  text-decoration: none !important;
}

.share-action:hover {
  background: #edf8ff;
}

.notification {
  color: var(--success);
  font: 12px Arial, sans-serif;
  margin-top: 10px;
}

.quality-card, .comparison-panel, .history-dashboard {
  margin: 14px 0;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(12, 35, 49, 0.92);
  color: var(--ink);
}

.quality-good { border-left: 5px solid var(--success); }
.quality-review { border-left: 5px solid var(--warning); }
.quality-poor { border-left: 5px solid var(--accent); }
.quality-stats { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
.quality-stats span { padding:7px 10px; border-radius:999px; background:rgba(148,196,220,.12); font-size:12px; }
.quality-card li { color:var(--muted); margin:5px 0; }
.comparison-head { display:flex; justify-content:space-between; gap:14px; align-items:center; margin-bottom:14px; }
.comparison-head strong { display:block; margin-top:6px; font-size:22px; }
.history-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-bottom:16px; }
.history-metrics div { background:rgba(148,196,220,.1); border-radius:12px; padding:13px; }
.history-metrics span { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; }
.history-metrics strong { display:block; margin-top:7px; font-size:24px; }
.history-table-wrap { overflow-x:auto; }
.history-table { width:100%; border-collapse:collapse; font-size:12px; color:var(--ink); }
.history-table th, .history-table td { padding:10px; border-bottom:1px solid rgba(148,196,220,.16); text-align:left; }
.history-table th { color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.history-empty { text-align:center !important; color:var(--muted); }

.safety-alert {
  background: #fff5e8;
  border-left: 4px solid var(--accent);
  padding: 13px 15px;
  margin: 14px 0;
  color: #7d5728;
  font: 13px/1.5 Arial, sans-serif;
  border-radius: 12px;
}

.chat-panel {
  position: fixed !important;
  right: 22px;
  bottom: 22px;
  z-index: 50;
  width: min(360px, calc(100vw - 44px));
  margin: 0 !important;
  background: rgba(7, 27, 36, 0.98) !important;
  border: 1px solid rgba(169, 240, 213, 0.45) !important;
  border-radius: 16px !important;
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.35) !important;
}
.chat-panel > .label-wrap { color: #f4fbf8 !important; }
.chat-panel .wrap { background: transparent !important; }

@media (max-width: 700px) {
  .chat-panel { right: 10px; bottom: 10px; width: calc(100vw - 20px); }
  .hero-hospital { flex-direction: column; align-items: flex-start; }
  .hero-left, .hero-right { max-width: none; width: 100%; }
  .hero-right { align-items: flex-start; }
  .panel { padding: 16px; }
  .result-heading { font-size: 31px; }
  .result-meta { align-items: flex-start; flex-direction: column; }
}
"""


def _demo_login(email, password, captcha_entry, captcha_answer):
    email_text = str(email or "").strip()
    password_text = str(password or "")
    strong_password = (
        len(password_text) >= 8
        and re.search(r"[A-Z]", password_text)
        and re.search(r"[a-z]", password_text)
        and re.search(r"\d", password_text)
        and re.search(r"[^A-Za-z0-9]", password_text)
    )
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_text) and strong_password and str(captcha_entry or "").strip() == str(captcha_answer or ""):
        return gr.update(visible=False), gr.update(visible=True), email_text, f'<div class="notification">Signed in. Reports will be addressed to {escape(email_text)}.</div>'
    message = "CAPTCHA answer is incorrect." if str(captcha_entry or "").strip() != str(captcha_answer or "") else "Use a valid email and a password with at least 8 characters, including uppercase, lowercase, number, and special character."
    return gr.update(visible=True), gr.update(visible=False), "", f'<div class="notice">{message}</div>'


def _continue_audio(audio_data, audio_file, audio_url):
    if audio_data is not None or audio_file is not None or str(audio_url or "").strip():
        return gr.update(visible=False), gr.update(visible=True), ""
    return gr.update(visible=True), gr.update(visible=False), '<div class="notice">Add a recording before moving to the next step.</div>'


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
    model = values[4] if len(values) > 4 else "AEROVA screening model"

    report_text = f"AEROVA respiratory screening report | Patient ID: {patient_id}\n" + re.sub(r"<[^>]+>", " ", result + " " + details)
    report_text = re.sub(r"\s+", " ", report_text).strip()[:1800]
    subject = f"AEROVA Respiratory Report - {patient_id}"
    email_link = f"mailto:{quote(str(email or ''))}?subject={quote(subject)}&body={quote(report_text)}"

    email_report = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;background:#edf3f7;font-family:Arial,sans-serif;color:#153448;">
  <div style="max-width:760px;margin:24px auto;background:#fff;border:1px solid #d7e3ea;border-radius:18px;overflow:hidden;box-shadow:0 14px 35px rgba(13,48,68,.12);">
    <div style="background:linear-gradient(135deg,#0b3852,#11879a);padding:28px 32px;color:#fff;">
      <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#bceaf0;">AEROVA</div>
      <h1 style="margin:8px 0 4px;font-size:28px;">Respiratory Screening Report</h1>
      <div style="font-size:13px;color:#d8f3f6;">Acoustic triage and clinical follow-up summary</div>
    </div>
    <div style="padding:28px 32px;">
      <table role="presentation" style="width:100%;border-collapse:collapse;background:#f4f9fb;border-radius:12px;">
        <tr><td style="padding:13px;border-bottom:1px solid #dce9ee;"><b>Patient ID</b><br><span style="color:#17788b;">{escape(patient_id)}</span></td>
            <td style="padding:13px;border-bottom:1px solid #dce9ee;"><b>Report date</b><br>{escape(report_date)}</td></tr>
        <tr><td style="padding:13px;"><b>Patient profile</b><br>{escape(str(age))} years · {escape(str(gender).title())}</td>
            <td style="padding:13px;"><b>Report recipient</b><br>{escape(str(email or 'Not provided'))}</td></tr>
      </table>
      <div style="margin-top:24px;padding:20px;border:1px solid #d9e7ed;border-left:5px solid #22a3b4;border-radius:12px;">
        {result}
      </div>
      <div style="margin-top:16px;padding:20px;border:1px solid #d9e7ed;border-radius:12px;">
        {details}
      </div>
      <div style="margin-top:16px;">{quality_markup}</div>
      <div style="margin-top:16px;">{comparison_markup}</div>
      <div style="margin-top:22px;padding:16px 18px;background:#fff6e8;border-left:4px solid #e58c45;border-radius:10px;color:#704b25;font-size:13px;line-height:1.55;">
        <b>Clinical notice:</b> This report is a screening aid and not a medical diagnosis or prescription. Severe breathing difficulty, chest pain, confusion, blue lips, or rapidly worsening symptoms require urgent medical attention.
      </div>
      <table role="presentation" style="width:100%;margin-top:30px;border-top:1px solid #dce7ec;padding-top:18px;">
        <tr><td style="padding-top:18px;color:#537080;font-size:12px;">Analysed with<br><b style="color:#153448;">{escape(str(model))}</b></td>
            <td style="padding-top:18px;text-align:right;color:#537080;font-size:12px;">Digitally generated by<br><b style="color:#153448;">AEROVA</b></td></tr>
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
        report_notice = f"<div class=\"notice\">Prediction completed. The downloadable PDF is unavailable: {escape(str(exc))}</div>"
      try:
        save_assessment({
          "patient_id": patient_id, "date": report_date, "label": metadata.get("label", "Readout"),
          "risk": metadata.get("risk", "unknown"), "confidence": float(metadata.get("confidence", 0)),
          "age": age, "gender": str(gender), "model": metadata.get("model", model),
        })
      except Exception as exc:
        report_notice += f"<div class=\"notice\">Prediction completed. History could not be saved: {escape(str(exc))}</div>"
    share_html = f'''<div class="share-actions">
        <a class="share-action" href="{escape(email_link)}">Open email draft</a>
        <a class="share-action" href="{escape(eml_link)}" download="aerova-{escape(patient_id.lower())}.eml">Download email file (.eml)</a>
        <a class="share-action" href="{escape(html_link)}" download="aerova-{escape(patient_id.lower())}.html">Download screening report</a>
      </div><p class="notification"><b>Report {escape(patient_id)}</b> is prepared for {escape(str(email))}. The .eml file preserves the designed AEROVA report layout.</p>{report_notice}'''
    if not extended:
      return (
        result,
        details + share_html,
        "",
        None,
        "",
        None,
        history_dashboard_html(),
        gr.update(visible=False),
        gr.update(visible=True),
      )
    return (
        result, details + share_html, quality_markup, chart_path, comparison_markup,
        pdf_path, history_dashboard_html(), gr.update(visible=False), gr.update(visible=True),
    )


def _safe_run_prediction(predict_fn, email, *values):
  try:
    return _run_prediction(predict_fn, email, *values)
  except Exception as exc:
    try:
      history = history_dashboard_html()
    except Exception:
      history = ""
    error_html = f'<div class="result-card result-error"><strong>Readout failed</strong><span>{escape(str(exc))}</span></div>'
    return error_html, "", "", None, "", None, history, gr.update(visible=True), gr.update(visible=False)


def build_app(predict_fn, model_files, default_model):
    with gr.Blocks(title="AEROVA | Respiratory sound check") as interface:
        with gr.Column(elem_classes=["login-shell"]) as login_view:
            gr.HTML('''<div class="login-panel">
                <div class="login-mark">AEROVA</div>
                <div class="eyebrow" style="margin-top: 18px; color: var(--secondary);">Hospital respiratory screening</div>
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
            ''')
            login_email = gr.Textbox(label="Email", placeholder="you@example.com")
            login_password = gr.Textbox(label="Password", type="password", placeholder="8+ chars: Aa1!")
            captcha_prompt, captcha_answer = _new_captcha()
            captcha_question = gr.Markdown(f"**{captcha_prompt}**")
            captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter the number")
            captcha_refresh = gr.Button("Refresh CAPTCHA", elem_classes=["secondary-button"])
            captcha_answer_state = gr.State(captcha_answer)
            login_button = gr.Button("Continue securely", variant="primary", elem_classes=["primary-button"])
            login_notice = gr.HTML()
            gr.HTML('<p class="login-note">Enter your email carefully. The final report email will be addressed directly to this address.</p></div>')

        with gr.Column(visible=False) as workspace:
            login_email_state = gr.State("")
            gr.HTML('''<header class="hero hero-hospital">
                <div class="hero-left">
                    <div class="brand-banner"><span class="brand-mark">+</span><span style="font-weight: 700; letter-spacing: .08em; text-transform: uppercase;">AEROVA</span></div>
                    <div class="eyebrow" style="margin-top: 18px; color: rgba(255,255,255,0.84);">Respiratory triage unit</div>
                    <h1>Acoustic screening for early respiratory health review</h1>
                    <p>Guided assessment from recording intake to clinical risk summary, designed for a modern hospital workflow.</p>
                </div>
                <div class="hero-right">
                    <div class="status-badges">
                        <span class="portal-chip"><span class="portal-dot"></span>Live triage</span>
                        <span class="portal-chip"><span class="portal-dot"></span>ER watch</span>
                    </div>
                </div>
            </header>''')
            with gr.Accordion("Patient history dashboard", open=False):
                with gr.Row():
                    history_search = gr.Textbox(label="Find patient ID", placeholder="AUR-...")
                    history_refresh = gr.Button("Search / refresh", elem_classes=["secondary-button"])
                history_output = gr.HTML(value=history_dashboard_html())
            gr.HTML('<div class="progress"><div class="progress-item active">01 · Recording</div><div class="progress-item">02 · Context</div><div class="progress-item">03 · Readout</div></div>')
            with gr.Column(elem_classes=["panel"]) as audio_step:
                gr.HTML('<h2 class="panel-title">Bring a recording</h2><p class="panel-copy">A short, clear cough recording works best.</p>')
                audio_input = gr.Audio(type="filepath", sources=["upload", "microphone"], label="Upload or record", elem_classes=["audio-box"])
                file_input = gr.File(type="filepath", file_count="single", label="Or choose a sound/video file")
                url_input = gr.Textbox(label="Or paste a direct audio URL", placeholder="https://...")
                audio_notice = gr.HTML()
                continue_audio = gr.Button("Continue to context", variant="primary", elem_classes=["primary-button"])

            with gr.Column(visible=False, elem_classes=["panel"]) as context_step:
                gr.HTML('<h2 class="panel-title">Add a little context</h2><p class="panel-copy">These details help frame the audio signal. They are optional, but useful.</p>')
                manual_notes = gr.Textbox(label="How are you feeling?", placeholder="For example: dry cough, fatigue, sore throat...", lines=2)
                with gr.Row():
                    gender = gr.Dropdown(["male", "female", "unknown"], label="Gender", value="unknown")
                    age = gr.Slider(0, 100, step=1, label="Age", value=30)
                cough_detected = gr.Slider(0.0, 1.0, step=0.01, label="How likely is the sound a cough?", value=0.5)
                with gr.Row():
                    respiratory_condition = gr.Radio(["true", "false"], label="Respiratory condition", value="false")
                    fever_muscle_pain = gr.Radio(["true", "false"], label="Fever / body pain", value="false")
                model_choice = gr.Dropdown(choices=model_files, value=default_model, label="Analysis model", visible=False)
                with gr.Row(elem_classes=["step-actions"]):
                    back_audio = gr.Button("Back", elem_classes=["secondary-button"])
                    predict_button = gr.Button("Generate my readout", variant="primary", elem_classes=["primary-button"])

            with gr.Column(visible=False, elem_classes=["panel"]) as result_step:
                gr.HTML('<h2 class="panel-title">Your readout</h2><p class="panel-copy">A clear summary of the sound and context signals, ready for follow-up or clinical review.</p>')
                prediction_output = gr.HTML()
                quality_output = gr.HTML()
                details_output = gr.HTML()
                with gr.Accordion("Explainable spectrogram and confidence", open=True):
                    explanation_chart = gr.Image(label="Acoustic explanation", interactive=False)
                with gr.Accordion("Model comparison", open=False):
                    model_comparison_output = gr.HTML()
                pdf_report = gr.File(label="Download PDF report with verification QR", interactive=False)
                with gr.Row(elem_classes=["result-actions"]):
                    back_result = gr.Button("Back to context", elem_classes=["secondary-button"])
                    new_assessment = gr.Button("End assessment", elem_classes=["secondary-button"])
                gr.HTML('<div class="safety-alert"><strong>When to seek care:</strong> severe breathing difficulty, chest pain, confusion, blue lips, or rapidly worsening symptoms require urgent medical attention.</div>')
                gr.HTML('<p class="footnote">This is a screening aid, not a diagnosis. If you feel seriously unwell or have trouble breathing, seek medical care promptly.</p>')
            with gr.Accordion("AEROVA respiratory assistant", open=False):
                gr.Markdown("Ask about AEROVA results, audio quality, reports, models, privacy, or urgent-care guidance.")
                chatbot = gr.Chatbot(label="AEROVA assistant", height=280)
                with gr.Row():
                    chat_input = gr.Textbox(label="Message", placeholder="How does AEROVA interpret a healthy result?", scale=5)
                    chat_send = gr.Button("Ask", variant="primary", scale=1)

            login_button.click(_demo_login, [login_email, login_password, captcha_entry, captcha_answer_state], [login_view, workspace, login_email_state, login_notice])
            captcha_refresh.click(lambda: _new_captcha(), outputs=[captcha_question, captcha_answer_state])
            chat_send.click(_chat_response, [chat_input, chatbot], [chatbot, chat_input])
            chat_input.submit(_chat_response, [chat_input, chatbot], [chatbot, chat_input])
        history_refresh.click(history_dashboard_html, [history_search], [history_output])
        continue_audio.click(_continue_audio, [audio_input, file_input, url_input], [audio_step, context_step, audio_notice])
        back_audio.click(lambda: (gr.update(visible=True), gr.update(visible=False)), outputs=[audio_step, context_step])
        back_result.click(lambda: (gr.update(visible=False), gr.update(visible=True)), outputs=[result_step, context_step])
        new_assessment.click(lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", ""), outputs=[result_step, audio_step, context_step, prediction_output, details_output])
        predict_button.click(
          lambda email, *values: _safe_run_prediction(predict_fn, email, *values),
            inputs=[login_email_state, audio_input, file_input, url_input, manual_notes, model_choice, gender, age, cough_detected, respiratory_condition, fever_muscle_pain],
            outputs=[prediction_output, details_output, quality_output, explanation_chart, model_comparison_output, pdf_report, history_output, context_step, result_step],
        )
    return interface
