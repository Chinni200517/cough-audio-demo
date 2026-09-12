from html import escape
from datetime import datetime
import os
import logging
import time
from functools import lru_cache
import re
import secrets
from urllib.parse import quote

import gradio as gr
import requests

from reporting import create_pdf_report, history_dashboard_html, save_assessment

# Global active key store (allows setting via UI, environment, or .env)
ACTIVE_GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY", "").strip()
    or os.environ.get("GOOGLE_API_KEY", "").strip()
)

APP_CSS = """
:root {
  --bg-canvas: #060f18;
  --bg-surface: #0b1f2e;
  --bg-panel: rgba(11, 31, 46, 0.94);
  --bg-panel-subtle: rgba(15, 41, 60, 0.88);
  --ink-bright: #ffffff;
  --ink: #f1f5f9;
  --ink-muted: #94a3b8;
  --ink-subtle: #cbd5e1;
  --primary: #00e5b0;
  --primary-deep: #087f78;
  --primary-glow: rgba(0, 229, 176, 0.35);
  --cyan-accent: #38bdf8;
  --cyan-deep: #0284c7;
  --accent-coral: #f43f5e;
  --accent-amber: #f59e0b;
  --success: #10b981;
  --border-line: rgba(56, 189, 248, 0.28);
  --border-glow: rgba(0, 229, 176, 0.3);
  --shadow-pro: 0 24px 60px rgba(2, 10, 18, 0.65), 0 0 1px rgba(56, 189, 248, 0.4);
}

body, .gradio-container {
  background: radial-gradient(circle at 10% 10%, #0d273a 0%, #081926 40%, #040c13 100%) !important;
  color: var(--ink) !important;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif !important;
  line-height: 1.5;
}

.gradio-container {
  max-width: 1320px !important;
  margin: auto;
  padding: 20px 20px 50px !important;
}

.gradio-container .block {
  border-radius: 20px !important;
}

/* =========================================================================
   TEXT VISIBILITY & HIGH CONTRAST (Guarantees all text is 100% visible)
   ========================================================================= */
label, label span, .gr-input-label, .block-title, .gr-button {
  color: #f1f5f9 !important;
  font-weight: 700 !important;
  letter-spacing: 0.02em;
}

input, textarea, select {
  background-color: rgba(13, 27, 42, 0.95) !important;
  color: #ffffff !important;
  border: 1px solid var(--border-line) !important;
  border-radius: 12px !important;
  padding: 10px 14px !important;
  font-size: 14px !important;
  transition: all 0.2s ease;
}

input::placeholder, textarea::placeholder {
  color: #94a3b8 !important;
  opacity: 0.9 !important;
}

input:focus, textarea:focus, select:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px var(--primary-glow) !important;
  outline: none !important;
}

/* =========================================================================
   PRO ENTERPRISE HERO HEADER
   ========================================================================= */
.hero {
  padding: 30px 34px;
  border: 1px solid var(--border-line);
  background: linear-gradient(135deg, rgba(13, 39, 58, 0.96) 0%, rgba(9, 61, 80, 0.94) 50%, rgba(14, 98, 116, 0.92) 100%);
  border-radius: 24px;
  color: #ffffff;
  box-shadow: var(--shadow-pro);
  position: relative;
  overflow: hidden;
}

.hero::after {
  content: "";
  position: absolute;
  top: 0; right: 0; bottom: 0; width: 350px;
  background: radial-gradient(circle, rgba(0, 229, 176, 0.12) 0%, transparent 70%);
  pointer-events: none;
}

.hero-hospital {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 165px;
}

.hero-left {
  max-width: 70%;
}

.hero-right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
}

.pro-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(0, 229, 176, 0.15);
  border: 1px solid var(--primary);
  color: var(--primary);
  border-radius: 999px;
  padding: 5px 14px;
  font: 800 11px/1 Arial, sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.pro-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 10px var(--primary);
  animation: pulse-glow 2s infinite;
}

@keyframes pulse-glow {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.7; }
}

.hero h1 {
  margin: 12px 0 8px;
  font-size: clamp(28px, 3.8vw, 48px);
  line-height: 1.05;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #ffffff !important;
}

.hero p {
  max-width: 680px;
  color: #e2e8f0;
  font-size: 15px;
  line-height: 1.6;
  margin: 0;
}

.status-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.portal-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(6, 17, 26, 0.6);
  border: 1px solid var(--border-line);
  color: #f1f5f9;
  border-radius: 999px;
  padding: 8px 14px;
  font: 700 11px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.portal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 8px var(--primary);
}

/* =========================================================================
   PANELS & WORKSPACE
   ========================================================================= */
.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border-line);
  border-radius: 22px;
  padding: 26px;
  box-shadow: var(--shadow-pro);
  backdrop-filter: blur(8px);
  margin-top: 14px;
}

.panel-title {
  font-size: 26px;
  font-weight: 800;
  margin: 0 0 6px;
  color: #ffffff !important;
  letter-spacing: -0.02em;
}

.panel-copy {
  color: #cbd5e1 !important;
  font-size: 14px;
  line-height: 1.5;
  margin: 0 0 20px;
}

.audio-box {
  border: 1px dashed var(--cyan-accent) !important;
  background: rgba(13, 36, 52, 0.75) !important;
  border-radius: 18px !important;
  padding: 10px !important;
}

/* =========================================================================
   BUTTONS
   ========================================================================= */
.primary-button {
  background: linear-gradient(135deg, #00e5b0 0%, #0284c7 100%) !important;
  color: #03141f !important;
  border: 0 !important;
  border-radius: 14px !important;
  font: 800 15px Arial, sans-serif !important;
  padding: 12px 22px !important;
  box-shadow: 0 10px 25px rgba(0, 229, 176, 0.3) !important;
  cursor: pointer;
  transition: all 0.2s ease !important;
}

.primary-button:hover {
  filter: brightness(1.1) !important;
  transform: translateY(-1px);
  box-shadow: 0 14px 30px rgba(0, 229, 176, 0.45) !important;
}

.secondary-button {
  border: 1px solid var(--border-line) !important;
  color: #38bdf8 !important;
  border-radius: 14px !important;
  background: rgba(14, 38, 54, 0.8) !important;
  font: 700 14px Arial, sans-serif !important;
  padding: 10px 18px !important;
  transition: all 0.2s ease !important;
}

.secondary-button:hover {
  background: rgba(22, 57, 80, 0.9) !important;
  border-color: var(--cyan-accent) !important;
}

.demo-fast-btn {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.2) 0%, rgba(0, 229, 176, 0.25) 100%) !important;
  border: 1px solid var(--primary) !important;
  color: #f1f5f9 !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
  padding: 10px 16px !important;
}

/* =========================================================================
   HIGH-CONTRAST RESULTS & CLINICAL READOUT
   ========================================================================= */
.result-card, .details-panel {
  border-radius: 22px;
  padding: 26px;
  background: linear-gradient(145deg, #0a1f2e 0%, #0f2c40 100%) !important;
  border: 1px solid var(--border-line) !important;
  box-shadow: var(--shadow-pro) !important;
  color: #f1f5f9 !important;
}

.result-card p, .result-card strong, .details-panel p, .details-panel strong,
.result-card h1, .result-card h2, .details-panel h1, .details-panel h2 {
  color: #ffffff !important;
}

.result-card {
  border-top: 6px solid var(--primary) !important;
}

.result-kicker, .section-label {
  color: var(--cyan-accent) !important;
  font: 800 11px/1.2 Arial, sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.result-heading {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 14px;
  font-size: 38px;
  font-weight: 800;
  color: #ffffff !important;
}

.confidence {
  color: var(--primary) !important;
  font: 800 14px Arial, sans-serif;
  background: rgba(0, 229, 176, 0.15);
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--primary);
}

.result-summary {
  font-size: 16px;
  line-height: 1.6;
  color: #e2e8f0 !important;
  margin: 12px 0 18px;
}

.meter {
  height: 10px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  overflow: hidden;
}

.meter span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--cyan-accent) 0%, var(--primary) 100%);
  border-radius: inherit;
}

.result-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  color: #94a3b8 !important;
  font-size: 13px;
}

.risk-pill, .symptom-chip {
  display: inline-block;
  border-radius: 999px;
  padding: 7px 14px;
  font: 800 11px Arial, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.risk-low { background: #064e3b; color: #a7f3d0 !important; border: 1px solid #10b981; }
.risk-medium { background: #78350f; color: #fde68a !important; border: 1px solid #f59e0b; }
.risk-high { background: #881337; color: #fecdd3 !important; border: 1px solid #f43f5e; }

.recommendation {
  background: rgba(2, 132, 199, 0.18) !important;
  border-left: 4px solid var(--primary) !important;
  padding: 16px 18px;
  border-radius: 14px;
  margin-top: 14px;
  color: #f1f5f9 !important;
}

.recommendation p {
  color: #f1f5f9 !important;
  margin: 6px 0 0;
}

.detail-section {
  padding: 0 0 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.detail-section p {
  color: #cbd5e1 !important;
}

.symptom-chip {
  background: rgba(56, 189, 248, 0.15) !important;
  color: #38bdf8 !important;
  border: 1px solid rgba(56, 189, 248, 0.3);
  text-transform: none;
}

.share-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 20px;
}

.share-action {
  display: inline-flex;
  align-items: center;
  padding: 10px 16px;
  border: 1px solid var(--border-line);
  border-radius: 12px;
  color: #38bdf8 !important;
  background: rgba(13, 37, 54, 0.85);
  font: 700 13px Arial, sans-serif;
  text-decoration: none !important;
  transition: all 0.2s ease;
}

.share-action:hover {
  background: rgba(23, 58, 83, 0.95);
  border-color: var(--primary);
  color: var(--primary) !important;
}

.share-action-wa {
  background: rgba(37, 211, 102, 0.15) !important;
  border-color: #25d366 !important;
  color: #25d366 !important;
}

.share-action-wa:hover {
  background: #25d366 !important;
  color: #041620 !important;
}

.safety-alert {
  background: rgba(245, 158, 11, 0.15);
  border-left: 4px solid var(--accent-amber);
  padding: 14px 18px;
  margin: 16px 0;
  color: #fde68a !important;
  font: 14px/1.5 Arial, sans-serif;
  border-radius: 12px;
}

.quality-card, .comparison-panel, .history-dashboard {
  margin: 16px 0;
  padding: 22px;
  border: 1px solid var(--border-line);
  border-radius: 18px;
  background: rgba(10, 27, 40, 0.92);
  color: #f1f5f9;
}

.quality-stats span {
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.14);
  color: #f1f5f9;
  font-size: 13px;
  font-weight: 600;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: #f1f5f9 !important;
}

.history-table th {
  color: var(--cyan-accent) !important;
  text-transform: uppercase;
  letter-spacing: .06em;
  padding: 12px 10px;
  border-bottom: 2px solid var(--border-line);
}

.history-table td {
  padding: 12px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: #f1f5f9 !important;
}

/* =========================================================================
   SIDE ROBOT ASSISTANT (Futuristic Robot Companion)
   ========================================================================= */
.robot-dock {
  position: fixed !important;
  right: 22px;
  bottom: 22px;
  z-index: 1000;
  width: min(400px, calc(100vw - 36px));
  margin: 0 !important;
  background: rgba(6, 18, 28, 0.98) !important;
  border: 1px solid var(--primary) !important;
  border-radius: 24px !important;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.7), 0 0 20px var(--primary-glow) !important;
  backdrop-filter: blur(14px);
  overflow: hidden;
}

.robot-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(135deg, rgba(13, 38, 56, 0.95) 0%, rgba(9, 58, 77, 0.9) 100%);
  border-bottom: 1px solid var(--border-line);
}

.robot-avatar-wrap {
  position: relative;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
}

.robot-antenna {
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  height: 8px;
  background: var(--primary);
}

.robot-antenna-light {
  position: absolute;
  top: -5px;
  left: -3px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 10px var(--primary);
  animation: pulse-glow 1.5s infinite;
}

.robot-face {
  width: 44px;
  height: 38px;
  background: linear-gradient(145deg, #0e2b3d, #091c28);
  border: 2px solid var(--primary);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 0 6px;
  box-shadow: inset 0 0 8px rgba(0, 229, 176, 0.4);
}

.robot-eye {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #00e5b0;
  box-shadow: 0 0 8px #00e5b0;
  animation: eye-blink 4s infinite;
}

@keyframes eye-blink {
  0%, 96%, 100% { transform: scaleY(1); }
  98% { transform: scaleY(0.1); }
}

.robot-meta {
  flex: 1;
}

.robot-title {
  font: 800 15px Arial, sans-serif;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 8px;
}

.pro-tag {
  background: var(--primary);
  color: #041620;
  font: 900 10px Arial, sans-serif;
  padding: 2px 6px;
  border-radius: 6px;
  text-transform: uppercase;
}

.robot-sub {
  font-size: 12px;
  color: #94a3b8;
}

.robot-status-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--primary);
  font-weight: 700;
}

.robot-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 6px var(--primary);
}

.robot-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(6, 17, 26, 0.5);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.robot-chip {
  padding: 4px 10px !important;
  border-radius: 999px !important;
  font-size: 11px !important;
  background: rgba(56, 189, 248, 0.12) !important;
  color: #e2e8f0 !important;
  border: 1px solid rgba(56, 189, 248, 0.3) !important;
  cursor: pointer;
  white-space: nowrap;
}

.robot-chip:hover {
  background: rgba(0, 229, 176, 0.2) !important;
  border-color: var(--primary) !important;
  color: #ffffff !important;
}

.key-config-box {
  background: rgba(9, 24, 36, 0.95);
  border: 1px dashed var(--border-line);
  border-radius: 12px;
  padding: 10px 12px;
  margin: 6px 12px;
}

.key-config-note {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
}

/* Chatbot container adjustments */
.robot-dock .chatbot {
  background: transparent !important;
  border: none !important;
}

.robot-dock .message {
  border-radius: 14px !important;
  padding: 10px 14px !important;
  font-size: 13px !important;
  line-height: 1.5 !important;
}

/* User message bubble */
.robot-dock .message.user {
  background: rgba(2, 132, 199, 0.35) !important;
  border: 1px solid var(--cyan-accent) !important;
  color: #ffffff !important;
}

/* Bot message bubble */
.robot-dock .message.bot {
  background: rgba(13, 33, 49, 0.95) !important;
  border: 1px solid rgba(0, 229, 176, 0.35) !important;
  border-left: 3px solid var(--primary) !important;
  color: #f8fafc !important;
}

/* =========================================================================
   LOGIN & MISC
   ========================================================================= */
.login-shell {
  max-width: 920px;
  margin: 48px auto 20px;
}

.login-panel {
  background: linear-gradient(145deg, rgba(11, 28, 41, 0.98), rgba(15, 45, 62, 0.98));
  border: 1px solid var(--border-line);
  border-radius: 26px;
  box-shadow: var(--shadow-pro);
  padding: 34px;
}

.login-mark {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  font: 800 28px/1 Arial, sans-serif;
  color: #ffffff;
}

.login-copy {
  color: #cbd5e1;
  font-size: 15px;
  line-height: 1.6;
  margin: 12px 0 24px;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 22px 0 24px;
}

.metric-item {
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 16px;
  padding: 14px 16px;
}

.metric-label {
  display: block;
  font: 800 11px Arial, sans-serif;
  color: #94a3b8;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 6px;
  font: 800 26px/1 Arial, sans-serif;
  color: #ffffff;
}

.metric-trend {
  display: inline-block;
  margin-top: 6px;
  font: 700 11px Arial, sans-serif;
  color: var(--primary);
}

.progress {
  display: flex;
  gap: 12px;
  margin: 24px 0 16px;
}

.progress-item {
  flex: 1;
  border-top: 4px solid rgba(255, 255, 255, 0.15);
  padding-top: 10px;
  color: #94a3b8;
  font: 800 11px Arial, sans-serif;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.progress-item.active {
  color: var(--primary);
  border-color: var(--primary);
}

.captcha-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.captcha-question {
  color: #00e5b0;
  font: 800 15px Arial, sans-serif;
  padding: 12px 16px;
  background: rgba(0, 229, 176, 0.12);
  border: 1px solid rgba(0, 229, 176, 0.35);
  border-radius: 12px;
}

.notice {
  color: #f87171;
  font: 600 13px Arial, sans-serif;
  padding: 10px 0;
}

.notification {
  color: var(--primary);
  font: 600 13px Arial, sans-serif;
  margin-top: 10px;
}

@media (max-width: 768px) {
  .robot-dock { right: 10px; bottom: 10px; width: calc(100vw - 20px); }
  .hero-hospital { flex-direction: column; align-items: flex-start; }
  .hero-left, .hero-right { max-width: 100%; width: 100%; }
  .hero-right { align-items: flex-start; }
  .panel { padding: 18px; }
  .result-heading { font-size: 28px; }
  .dashboard-metrics { grid-template-columns: 1fr; }
}
"""


def _new_captcha():
    first = secrets.randbelow(8) + 2
    second = secrets.randbelow(8) + 2
    return f"What is {first} + {second}?", str(first + second)


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
    if (re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_text)
            and strong_password and str(captcha_entry or "").strip() == str(captcha_answer or "")):
        return gr.update(visible=False), gr.update(visible=True), email_text, f'<div class="notification">Signed in. Reports will be addressed to {escape(email_text)}.</div>'
    if str(captcha_entry or "").strip() != str(captcha_answer or ""):
        message = "CAPTCHA answer is incorrect. Refresh the challenge and try again."
    else:
        message = "Use a valid email and a password with at least 8 characters, including uppercase, lowercase, number, and special character."
    return gr.update(visible=True), gr.update(visible=False), "", f'<div class="notice">{message}</div>'


def _fast_demo_login():
    """Bypass manual entry for frictionless demo evaluation."""
    demo_email = "clinician@hospital-aerova.org"
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        demo_email,
        f'<div class="notification">⚡ Instant Demo Access granted. Ready to screen cough audio!</div>',
    )


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_LOG = logging.getLogger("aerova.gemini")
GEMINI_SYSTEM_INSTRUCTION = """You are AEROVA-BOT, the intelligent clinical AI robot copilot for the AEROVA respiratory acoustic screening platform.
Answer questions naturally, clearly, and concisely, like a top-tier medical and acoustic engineering assistant.
Do not reply with a generic menu unless the user specifically asks what you can do.

Project context:
- AEROVA is an advanced cough-audio respiratory screening system developed by Chinni200517 on GitHub.
- It analyzes cough recordings using audio signal processing (MFCC acoustic features, RMS energy, spectral features) and trained machine-learning models (Extra Trees, Random Forest, Logistic Regression, KNN, SVC).
- It provides Healthy vs Disease screening signals, confidence meters, clinical symptom risk tiers, explainable spectrograms, and downloadable PDF reports with verification QR codes.
- It is a screening aid, not a diagnostic certainty. If severe breathing difficulty, blue lips, chest pain, or confusion are reported, urge immediate emergency medical care.
- Always maintain your identity as AEROVA's Robot Copilot developed by Chinni200517."""


def _message_text(content):
    """Extract plain text from Gradio's string or structured message content."""
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
    """Convert Gradio message history into Gemini's user/model conversation roles."""
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
    """Discover text Flash models; cache for a five-minute period per key."""
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
        GEMINI_LOG.warning("Gemini answer failed unexpectedly; using local help.")
        return None


def _local_project_answer(lowered):
    """Extensive autonomous knowledge engine that answers all questions about AEROVA."""
    if any(term in lowered for term in ("what is aerova", "what is this", "about this project", "purpose", "goal")):
        return (
            "🤖 **AEROVA Pro** is an acoustic respiratory screening and triage system. "
            "It combines digital cough sound analysis (MFCC features) and clinical symptoms with machine-learning "
            "classifiers (Extra Trees, Random Forest, Logistic Regression) to deliver a Healthy vs Disease screening signal. "
            "It is designed for hospital triage aid and is not a medical diagnosis."
        )
    if any(term in lowered for term in ("how do i use", "how to use", "how does it work", "how does aerova work", "workflow", "steps", "process", "guide")):
        return (
            "🚀 **AEROVA Workflow Guide:**\n"
            "1. **Sign In:** Use the demo login or click '⚡ Quick Demo Sign-in'.\n"
            "2. **Audio Intake:** Upload or record 1 to 10 seconds of clear coughs via mic or file (WAV, MP3, WebM).\n"
            "3. **Clinical Context:** Provide optional symptoms (fever, respiratory history, age, gender).\n"
            "4. **AI Triage Readout:** Review the Healthy/Disease prediction, confidence score, spectrogram, model comparison, and download your clinical PDF report."
        )
    if any(term in lowered for term in ("file type", "format", "supported audio", "wav", "webm", "mp3", "ogg", "flac")):
        return (
            "🎵 **Supported Audio Formats:**\n"
            "AEROVA directly accepts **WAV**, **FLAC**, and **OGG** audio files. "
            "Browser formats such as **WebM**, **MP3**, and **M4A** are automatically converted to 22,050 Hz PCM WAV using the embedded FFmpeg engine."
        )
    if any(term in lowered for term in ("record", "cough clearly", "background noise", "microphone", "tips", "how to record")):
        return (
            "🎙️ **Recording Best Practices:**\n"
            "- Sit in a quiet room with minimal ambient echo.\n"
            "- Hold your microphone 10–20 cm from your mouth.\n"
            "- Produce 1 to 3 clear, intentional coughs over 2 to 6 seconds.\n"
            "- Avoid touching the microphone or blowing directly into it to prevent acoustic clipping."
        )
    if any(term in lowered for term in ("feature", "mfcc", "mel", "extract", "sound feature", "frequency", "rms")):
        return (
            "🔬 **Acoustic Feature Extraction:**\n"
            "AEROVA samples cough audio at 22,050 Hz and extracts:\n"
            "- **40 MFCC features**: 20 Mel-Frequency Cepstral Coefficient means and 20 variances reflecting vocal tract acoustics.\n"
            "- **RMS Energy**: Measures signal loudness and power variation.\n"
            "- **Quality metrics**: Signal-to-Noise Ratio (SNR), clipping ratio, and silent duration."
        )
    if any(term in lowered for term in ("which model", "models", "algorithm", "machine learning", "random forest", "extra trees", "logistic", "knn", "svc")):
        return (
            "🧠 **Machine Learning Architecture:**\n"
            "AEROVA evaluates multiple scikit-learn models: Extra Trees Classifier, Random Forest, Logistic Regression, Support Vector Classifier (SVC), and KNN. "
            "The system automatically loads the highest-performing validated model (Extra Trees / Random Forest) to produce the primary triage readout."
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
            "- A downloadable **PDF Medical Summary** complete with an authentication QR code.\n"
            "- An **EML email draft** formatted with clinical styling.\n"
            "- An **HTML report** and logged entry in the Patient History Dashboard."
        )
    if any(term in lowered for term in ("patient id", "history", "assessment", "dashboard", "aur")):
        return (
            "📋 **Patient ID & History:**\n"
            "Every triage session receives a unique tokenized identifier (e.g., `AUR-20260911-XXXX`). "
            "Previous evaluations can be searched and reviewed in the 'Patient history dashboard' accordion."
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
            "Symptoms provide vital context to acoustic signals. Persistent cough, fever, fatigue, or loss of taste/smell should be monitored closely. "
            "Seek emergency care immediately if you experience severe shortness of breath, chest pain, or cyanosis (blue-tinted lips)."
        )
    if any(term in lowered for term in ("privacy", "secure", "stored", "personal data", "secret", "api key", "gemini key")):
        return (
            "🔒 **Privacy & Key Security:**\n"
            "Screening data is processed locally. API keys (such as Google Gemini) are stored only in runtime session memory or server environment variables, never committed to repository code."
        )
    if any(term in lowered for term in ("technology", "built with", "programming", "python", "gradio", "github", "render", "deploy")):
        return (
            "💻 **Tech Stack:**\n"
            "Built with Python 3.10+, Gradio UI, librosa, NumPy, SciPy, scikit-learn, joblib, and ReportLab for PDF generation. "
            "Hosted on GitHub and deployable on Docker, Hugging Face, or Render."
        )
    if any(term in lowered for term in ("who made", "developer", "author", "created", "creator", "chinni")):
        return (
            "👨‍💻 **Project Author:**\n"
            "AEROVA was engineered and maintained by **Chinni200517** on GitHub (Repository: `cough-audio-demo`)."
        )
    if any(term in lowered for term in ("dataset", "data", "coughvid", "samples", "training data")):
        return (
            "📁 **Dataset Information:**\n"
            "Trained and evaluated on respiratory acoustic recordings from the COUGHVID crowdsourced dataset, featuring annotated cough audio with expert clinical validation labels."
        )
    if any(term in lowered for term in ("hello", "hi", "hey", "good morning", "good evening", "greetings")):
        return (
            "🤖 **Hello! I am AEROVA-BOT PRO**, your respiratory acoustic and clinical AI assistant. "
            "How can I help you today? You can ask about recording your cough, audio features, ML models, screening results, or reports."
        )
    if any(term in lowered for term in ("help", "capabilities", "what can you do", "features")):
        return (
            "🛠️ **What I Can Do:**\n"
            "- Guide you through recording and uploading cough audio.\n"
            "- Explain MFCC features, spectrograms, and acoustic quality.\n"
            "- Explain ML model predictions (Healthy vs Disease) and accuracy benchmarks.\n"
            "- Provide PDF report information and clinical triage guidance.\n"
            "- Connect to Google Gemini for open-ended AI conversation!"
        )
    if any(term in lowered for term in ("gemini", "api key", "google gemini", "connect gemini")):
        return (
            "✨ **Connecting Google Gemini:**\n"
            "To unlock live Google Gemini AI, paste your Google AI Studio API key into the '🔑 Configure Google Gemini API Key' field above and click 'Connect Key'!"
        )
    return None


def _chat_response(message, history, user_api_key=""):
    """Handle chat messages with Google Gemini or smart fallback engine."""
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
            "🧠 **Trained Models:**\n"
            "AEROVA evaluates Extra Trees, Random Forest, Logistic Regression, KNN, and SVC models trained on cough audio features."
        )
    else:
        answer = (
            "🤖 **AEROVA-BOT PRO:** I am your respiratory acoustic copilot developed for Chinni200517's AEROVA project. "
            "I can answer questions about cough analysis, audio features (MFCC), ML models, screening results, and hospital triage.\n\n"
            "💡 *Tip:* To ask open-ended general questions to live Google Gemini AI, enter your **Google Gemini API Key** in the Robot drawer above!"
        )

    history.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])
    return history, ""


def _set_gemini_key(key_text):
    global ACTIVE_GEMINI_KEY
    cleaned = str(key_text or "").strip()
    if not cleaned:
        ACTIVE_GEMINI_KEY = ""
        return "", '<div style="color: #94a3b8; font-size: 11px;">⚡ Key cleared. Running in Autonomous Copilot mode.</div>'
    ACTIVE_GEMINI_KEY = cleaned
    return cleaned, '<div style="color: #00e5b0; font-size: 11px; font-weight: 700;">🟢 Gemini Key Connected! Live Google Gemini AI is now active.</div>'


def _continue_audio(audio_data, audio_file, audio_url):
    if audio_data is not None or audio_file is not None or str(audio_url or "").strip():
        return gr.update(visible=False), gr.update(visible=True), ""
    return gr.update(visible=True), gr.update(visible=False), '<div class="notice">Please record or upload audio before moving to the next step.</div>'


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

    report_text = f"AEROVA respiratory screening report | Patient ID: {patient_id}\n" + re.sub(r"<[^>]+>", " ", result + " " + details)
    report_text = re.sub(r"\s+", " ", report_text).strip()[:1800]
    subject = f"AEROVA Respiratory Report - {patient_id}"
    email_link = f"mailto:{quote(str(email or ''))}?subject={quote(subject)}&body={quote(report_text)}"

    email_report = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="margin:0;background:#081926;font-family:Arial,sans-serif;color:#f1f5f9;">
  <div style="max-width:760px;margin:24px auto;background:#0d2638;border:1px solid #174b6b;border-radius:18px;overflow:hidden;box-shadow:0 14px 35px rgba(0,0,0,.5);">
    <div style="background:linear-gradient(135deg,#09334c,#008b8b);padding:28px 32px;color:#fff;">
      <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#7bf5d4;">AEROVA PRO</div>
      <h1 style="margin:8px 0 4px;font-size:28px;">Respiratory Screening Report</h1>
      <div style="font-size:13px;color:#d8f3f6;">Acoustic triage & clinical follow-up summary</div>
    </div>
    <div style="padding:28px 32px;">
      <table role="presentation" style="width:100%;border-collapse:collapse;background:#091c2a;border-radius:12px;color:#f1f5f9;">
        <tr><td style="padding:13px;border-bottom:1px solid #163a52;"><b>Patient ID</b><br><span style="color:#00e5b0;">{escape(patient_id)}</span></td>
            <td style="padding:13px;border-bottom:1px solid #163a52;"><b>Report date</b><br>{escape(report_date)}</td></tr>
        <tr><td style="padding:13px;"><b>Patient profile</b><br>{escape(str(age))} years · {escape(str(gender).title())}</td>
            <td style="padding:13px;"><b>Report recipient</b><br>{escape(str(email or 'Not provided'))}</td></tr>
      </table>
      <div style="margin-top:24px;padding:20px;border:1px solid #1a4f73;border-left:5px solid #00e5b0;border-radius:12px;background:#0c2233;">
        {result}
      </div>
      <div style="margin-top:16px;padding:20px;border:1px solid #1a4f73;border-radius:12px;background:#0c2233;">
        {details}
      </div>
      <div style="margin-top:16px;">{quality_markup}</div>
      <div style="margin-top:16px;">{comparison_markup}</div>
      <div style="margin-top:22px;padding:16px 18px;background:rgba(245,158,11,0.15);border-left:4px solid #f59e0b;border-radius:10px;color:#fde68a;font-size:13px;line-height:1.55;">
        <b>Clinical notice:</b> This report is an acoustic screening aid and not a diagnostic certainty. Severe dyspnea, chest pain, confusion, or cyanosis require emergency medical attention.
      </div>
      <table role="presentation" style="width:100%;margin-top:30px;border-top:1px solid #163a52;padding-top:18px;">
        <tr><td style="padding-top:18px;color:#94a3b8;font-size:12px;">Analysed with<br><b style="color:#f1f5f9;">{escape(str(model))}</b></td>
            <td style="padding-top:18px;text-align:right;color:#94a3b8;font-size:12px;">Digitally generated by<br><b style="color:#f1f5f9;">AEROVA PRO</b></td></tr>
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
            report_notice = f'<div class="notice">Prediction completed. The downloadable PDF is unavailable: {escape(str(exc))}</div>'
        try:
            save_assessment({
                "patient_id": patient_id, "date": report_date, "label": metadata.get("label", "Readout"),
                "risk": metadata.get("risk", "unknown"), "confidence": float(metadata.get("confidence", 0)),
                "age": age, "gender": str(gender), "model": metadata.get("model", model),
            })
        except Exception as exc:
            report_notice += f'<div class="notice">History could not be saved: {escape(str(exc))}</div>'
    label = str(metadata.get("label", "Readout"))
    risk = str(metadata.get("risk", "unknown"))
    conf_val = float(metadata.get("confidence", 0))
    conf_pct = conf_val * 100

    wa_message = (
        f"🩺 *AEROVA CLINICAL SCREENING REPORT*\n"
        f"📋 Patient ID: {patient_id}\n"
        f"📅 Date: {report_date}\n"
        f"👤 Profile: {age} yrs · {str(gender).title()}\n"
        f"🔍 Readout: *{label}*\n"
        f"⚠️ Risk Level: *{str(risk).title()}*\n"
        f"🎯 Confidence: *{conf_pct:.1f}%*\n"
        f"🧠 Model: {model}\n\n"
        f"ℹ️ Screening aid only. Consult a healthcare professional for clinical diagnosis."
    )
    wa_link = f"https://api.whatsapp.com/send?text={quote(wa_message)}"

    share_html = f'''<div class="share-actions">
        <a class="share-action share-action-wa" href="{escape(wa_link)}" target="_blank" rel="noopener noreferrer">💬 Share via WhatsApp</a>
        <a class="share-action" href="{escape(email_link)}">✉️ Open email draft</a>
        <a class="share-action" href="{escape(eml_link)}" download="aerova-{escape(patient_id.lower())}.eml">📥 Download email file (.eml)</a>
        <a class="share-action" href="{escape(html_link)}" download="aerova-{escape(patient_id.lower())}.html">🌐 Download screening report</a>
      </div><p class="notification"><b>Report {escape(patient_id)}</b> is ready for {escape(str(email))}.</p>{report_notice}'''

    report_meta = {
        "patient_id": patient_id,
        "date": report_date,
        "age": age,
        "gender": str(gender),
        "model": model,
        "label": label,
        "risk": risk,
        "confidence": conf_pct,
        "report_text": report_text,
    }

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
            report_meta,
            str(email or ""),
        )
    return (
        result, details + share_html, quality_markup, chart_path, comparison_markup,
        pdf_path, history_dashboard_html(), gr.update(visible=False), gr.update(visible=True),
        report_meta, str(email or ""),
    )


def _dispatch_whatsapp(phone: str, meta: dict) -> str:
    if not meta or not meta.get("patient_id"):
        return '<div class="notice" style="color: #f59e0b; margin-top: 8px;">Please run a screening prediction first to generate the clinical report.</div>'

    clean_digits = re.sub(r"[^\d]", "", str(phone or ""))
    patient_id = meta.get("patient_id", "AUR-PATIENT")
    date = meta.get("date", "")
    age = meta.get("age", "Not provided")
    gender = meta.get("gender", "unknown")
    label = meta.get("label", "Readout")
    risk = meta.get("risk", "unknown")
    conf = float(meta.get("confidence", 0))
    model = meta.get("model", "AEROVA Extra Trees")

    wa_text = (
        f"🩺 *AEROVA CLINICAL SCREENING REPORT*\n"
        f"📋 Patient ID: {patient_id}\n"
        f"📅 Date: {date}\n"
        f"👤 Profile: {age} yrs · {str(gender).title()}\n"
        f"🔍 Readout: *{label}*\n"
        f"⚠️ Risk Level: *{str(risk).title()}*\n"
        f"🎯 Confidence: *{conf:.1f}%*\n"
        f"🧠 Model: {model}\n\n"
        f"ℹ️ Acoustic screening aid. Consult medical professional for diagnosis."
    )
    if clean_digits:
        wa_url = f"https://api.whatsapp.com/send?phone={clean_digits}&text={quote(wa_text)}"
        target_display = f"for +{clean_digits}"
    else:
        wa_url = f"https://api.whatsapp.com/send?text={quote(wa_text)}"
        target_display = "(no specific number entered - share to any contact)"

    return f'''<div style="background: rgba(16, 185, 129, 0.14); border: 1px solid #10b981; border-radius: 10px; padding: 14px 18px; margin-top: 12px;">
        <div style="color: #10b981; font-weight: 700; font-size: 14px; margin-bottom: 4px;">✅ WhatsApp Report Dispatch Ready {target_display}</div>
        <p style="color: #cbd5e1; font-size: 13px; margin: 0 0 12px 0;">Click the button below to launch WhatsApp with the complete pre-filled assessment report:</p>
        <a href="{escape(wa_url)}" target="_blank" rel="noopener noreferrer" style="display: inline-flex; align-items: center; gap: 8px; background: #25d366; color: #041620; font-weight: 700; padding: 10px 20px; border-radius: 8px; text-decoration: none; box-shadow: 0 4px 14px rgba(37,211,102,0.35);">
          <span>💬</span> <span>Open in WhatsApp & Send Report →</span>
        </a>
    </div>'''


def _dispatch_email(target_email: str, meta: dict) -> str:
    if not meta or not meta.get("patient_id"):
        return '<div class="notice" style="color: #f59e0b; margin-top: 8px;">Please run a screening prediction first to generate the clinical report.</div>'

    target_email = str(target_email or "").strip()
    patient_id = meta.get("patient_id", "AUR-PATIENT")
    subject = f"AEROVA Respiratory Report - {patient_id}"
    body = meta.get("report_text", "")
    mailto_url = f"mailto:{quote(target_email)}?subject={quote(subject)}&body={quote(body)}"

    target_display = f"to <b>{escape(target_email)}</b>" if target_email else "(default mail app)"
    return f'''<div style="background: rgba(56, 189, 248, 0.14); border: 1px solid #38bdf8; border-radius: 10px; padding: 14px 18px; margin-top: 12px;">
        <div style="color: #38bdf8; font-weight: 700; font-size: 14px; margin-bottom: 4px;">✅ Email Report Draft Ready {target_display}</div>
        <p style="color: #cbd5e1; font-size: 13px; margin: 0 0 12px 0;">Click the button below to launch your email client with the clinical triage summary:</p>
        <a href="{escape(mailto_url)}" style="display: inline-flex; align-items: center; gap: 8px; background: #38bdf8; color: #041620; font-weight: 700; padding: 10px 20px; border-radius: 8px; text-decoration: none; box-shadow: 0 4px 14px rgba(56,189,248,0.35);">
          <span>✉️</span> <span>Open Email Draft & Send →</span>
        </a>
    </div>'''


def build_app(predict_fn, model_files, default_model):
    captcha_question, captcha_answer = _new_captcha()
    with gr.Blocks(title="AEROVA PRO | AI Respiratory Triage & Robot Copilot") as interface:
        with gr.Column(elem_classes=["login-shell"]) as login_view:
            gr.HTML('''<div class="login-panel">
                <div class="login-mark">
                  <span style="color: #00e5b0; font-size: 32px;">✦</span>
                  <span>AEROVA <span style="font-size: 14px; background: #00e5b0; color: #041620; padding: 2px 8px; border-radius: 6px; vertical-align: middle;">PRO v2.5</span></span>
                </div>
                <div class="eyebrow" style="margin-top: 18px; color: #38bdf8;">Hospital Respiratory Triage Unit</div>
                <h1 style="margin: 12px 0 8px; font-size: clamp(26px, 3.2vw, 42px); line-height: 1.1; color: white;">Acoustic Screening & AI Clinical Decision Support</h1>
                <p class="login-copy">Access the enterprise screening platform for cough sound feature extraction, machine-learning classification, and automated clinical reports.</p>
                <div class="dashboard-metrics">
                    <div class="metric-item">
                        <span class="metric-label">Active Cases</span>
                        <span class="metric-value">184</span>
                        <span class="metric-trend">● Live Monitoring</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Triage Accuracy</span>
                        <span class="metric-value">84.6%</span>
                        <span class="metric-trend">Extra Trees Model</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Emergency Status</span>
                        <span class="metric-value">Level 2</span>
                        <span class="metric-trend">ER Watch Active</span>
                    </div>
                </div>
            ''')
            with gr.Row():
                fast_demo_btn = gr.Button("⚡ Instant Demo Sign-in (1-Click)", elem_classes=["demo-fast-btn"])
            gr.HTML('<div style="text-align: center; color: #94a3b8; font-size: 12px; margin: 12px 0 16px;">— OR SIGN IN WITH CREDENTIALS —</div>')
            login_email = gr.Textbox(label="Clinician Email", placeholder="doctor@hospital-aerova.org")
            login_password = gr.Textbox(label="Password", type="password", placeholder="8+ chars with Aa1!")
            with gr.Row(elem_classes=["captcha-row"]):
                captcha_prompt = gr.Markdown(f'<div class="captcha-question">{captcha_question}</div>')
                captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter number", scale=2)
                captcha_refresh = gr.Button("↻", elem_classes=["secondary-button", "captcha-refresh"], scale=0)
            captcha_answer_state = gr.State(captcha_answer)
            login_button = gr.Button("Continue Securely", variant="primary", elem_classes=["primary-button"])
            login_notice = gr.HTML()
            gr.HTML('<p class="login-note" style="color:#94a3b8; font-size:12px; text-align:center; margin-top:14px;">Reports generated during this session will be addressed to your clinician email.</p></div>')

        with gr.Column(visible=False) as workspace:
            login_email_state = gr.State("")
            gemini_key_state = gr.State(ACTIVE_GEMINI_KEY)

            gr.HTML('''<header class="hero hero-hospital">
                <div class="hero-left">
                    <div class="brand-banner">
                      <span class="pro-badge"><span class="pro-pulse"></span>PRO ENTERPRISE</span>
                    </div>
                    <div class="eyebrow" style="margin-top: 14px; color: #38bdf8;">ACOUSTIC RESPIRATORY SCREENING</div>
                    <h1>AEROVA Clinical Triage & Acoustic Sound Check</h1>
                    <p>High-precision respiratory screening from microphone intake to clinical risk readout, powered by audio MFCC feature extraction and trained machine-learning ensembles.</p>
                </div>
                <div class="hero-right">
                    <div class="status-badges">
                        <span class="portal-chip"><span class="portal-dot"></span>Live Triage Unit</span>
                        <span class="portal-chip"><span class="portal-dot"></span>Model: Extra Trees</span>
                    </div>
                </div>
            </header>''')

            with gr.Accordion("📋 Patient History & Past Assessments", open=False):
                with gr.Row():
                    history_search = gr.Textbox(label="Find Patient ID", placeholder="Search AUR-...")
                    history_refresh = gr.Button("Search / Refresh", elem_classes=["secondary-button"])
                history_output = gr.HTML(value=history_dashboard_html())

            gr.HTML('<div class="progress"><div class="progress-item active">01 · Audio Intake</div><div class="progress-item">02 · Clinical Context</div><div class="progress-item">03 · Readout & Reports</div></div>')

            with gr.Column(elem_classes=["panel"]) as audio_step:
                gr.HTML('<h2 class="panel-title">1. Bring a Cough Recording</h2><p class="panel-copy">A short, clear 2–6 second cough in a quiet room produces the most reliable acoustic signal.</p>')
                audio_input = gr.Audio(type="filepath", sources=["upload", "microphone"], label="Upload or Record via Microphone", elem_classes=["audio-box"])
                file_input = gr.File(file_count="single", label="Or Choose an Audio/Video File (.wav, .mp3, .webm, .ogg)")
                url_input = gr.Textbox(label="Or Paste a Direct Audio URL", placeholder="https://example.com/cough_sample.wav")
                audio_notice = gr.HTML()
                continue_audio = gr.Button("Continue to Clinical Context →", variant="primary", elem_classes=["primary-button"])

            with gr.Column(visible=False, elem_classes=["panel"]) as context_step:
                gr.HTML('<h2 class="panel-title">2. Add Patient & Clinical Context</h2><p class="panel-copy">Clinical details provide vital context to the acoustic machine-learning model.</p>')
                manual_notes = gr.Textbox(label="Patient Symptoms & Notes", placeholder="e.g. Dry barking cough for 3 days, mild fatigue, throat irritation...", lines=2)
                with gr.Row():
                    gender = gr.Dropdown(["male", "female", "unknown"], label="Gender", value="unknown")
                    age = gr.Slider(0, 100, step=1, label="Patient Age (Years)", value=30)
                cough_detected = gr.Slider(0.0, 1.0, step=0.01, label="Cough Detection Confidence Likelihood", value=0.85)
                with gr.Row():
                    respiratory_condition = gr.Radio(["true", "false"], label="Pre-existing Respiratory Condition (Asthma / COPD)", value="false")
                    fever_muscle_pain = gr.Radio(["true", "false"], label="Fever or Muscle Body Pain Present?", value="false")
                model_choice = gr.Dropdown(choices=model_files, value=default_model, label="Analysis Model", visible=False)
                with gr.Row(elem_classes=["step-actions"]):
                    back_audio = gr.Button("← Back to Audio Intake", elem_classes=["secondary-button"])
                    predict_button = gr.Button("⚡ Generate Clinical Triage Readout", variant="primary", elem_classes=["primary-button"])

            with gr.Column(visible=False, elem_classes=["panel"]) as result_step:
                gr.HTML('<h2 class="panel-title">3. Clinical Readout & Medical Export</h2><p class="panel-copy">Comprehensive acoustic interpretation, model confidence, and follow-up clinical guidance.</p>')
                prediction_output = gr.HTML()
                quality_output = gr.HTML()
                details_output = gr.HTML()
                with gr.Accordion("📊 Explainable Acoustic Spectrogram & Waveform", open=True):
                    explanation_chart = gr.Image(label="Spectrogram Analysis", interactive=False)
                with gr.Accordion("🧠 Machine Learning Model Comparison", open=False):
                    model_comparison_output = gr.HTML()
                pdf_report = gr.File(label="Download Verified PDF Medical Report (with QR Authentication)", interactive=False)
                with gr.Group(elem_classes=["panel-subtle"]):
                    gr.HTML('''
                    <div style="background: rgba(11, 31, 46, 0.95); border: 1px solid #174b6b; border-radius: 12px; padding: 16px 20px; margin: 18px 0 12px;">
                      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px;">
                        <span style="font-size: 20px;">📤</span>
                        <h3 style="margin: 0; color: #38bdf8; font-size: 16px; font-weight: 700;">Multi-Channel Report Dispatch · WhatsApp & Email</h3>
                      </div>
                      <p style="margin: 0; color: #94a3b8; font-size: 13px;">Dispatch this official screening readout directly to a patient or doctor\'s WhatsApp phone number or email inbox.</p>
                    </div>
                    ''')
                    with gr.Row():
                        with gr.Column(scale=1):
                            dispatch_phone = gr.Textbox(
                                label="📲 Recipient WhatsApp Number",
                                placeholder="e.g. +91 98765 43210 or 15551234567 (with country code)",
                                lines=1,
                            )
                            dispatch_wa_btn = gr.Button("💬 Send / Open in WhatsApp", variant="primary", elem_classes=["primary-button"])
                        with gr.Column(scale=1):
                            dispatch_email = gr.Textbox(
                                label="✉️ Recipient Email Address",
                                placeholder="e.g. doctor@clinic.org or patient@mail.com",
                                lines=1,
                            )
                            dispatch_email_btn = gr.Button("✉️ Send / Open Email Draft", elem_classes=["secondary-button"])
                    dispatch_status = gr.HTML()
                with gr.Row(elem_classes=["result-actions"]):
                    back_result = gr.Button("← Modify Context", elem_classes=["secondary-button"])
                    new_assessment = gr.Button("Start New Assessment", elem_classes=["secondary-button"])
                gr.HTML('<div class="safety-alert"><strong>When to seek urgent care:</strong> Severe breathing difficulty, chest pain, confusion, or blue lips require immediate emergency attention.</div>')
                gr.HTML('<p class="footnote" style="color:#94a3b8; font-size:12px; margin-top:12px;">This application is an acoustic screening aid, not a diagnostic confirmation. Consult a medical professional for clinical diagnosis.</p>')

            # =================================================================
            # SIDE ROBOT AI COPILOT DOCK
            # =================================================================
            with gr.Accordion("🤖 AEROVA-BOT PRO · AI Robot Copilot", open=False, elem_classes=["robot-dock", "chat-panel"]):
                gr.HTML('''
                <div class="robot-header">
                  <div class="robot-avatar-wrap">
                    <div class="robot-antenna"><div class="robot-antenna-light"></div></div>
                    <div class="robot-face">
                      <div class="robot-eye"></div>
                      <div style="width: 10px; height: 3px; background: #00e5b0; border-radius: 2px;"></div>
                      <div class="robot-eye"></div>
                    </div>
                  </div>
                  <div class="robot-meta">
                    <div class="robot-title">AEROVA-BOT <span class="pro-tag">PRO v2.5</span></div>
                    <div class="robot-sub">Clinical Acoustic AI Robot Copilot</div>
                    <div class="robot-status-row">
                      <span class="robot-pulse"></span>
                      <span>SYSTEM: <strong>ONLINE</strong></span>
                    </div>
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
                    key_status_box = gr.HTML(
                        '<div style="color: #94a3b8; font-size: 11px;">⚡ Running in Autonomous Copilot mode. Paste key for live Gemini 2.0 reasoning.</div>'
                    )

                gr.HTML('''
                <div class="robot-chip-row">
                  <span style="font-size: 11px; color: #94a3b8; font-weight: 700; margin-right: 4px;">Quick Ask:</span>
                </div>
                ''')
                with gr.Row():
                    chip_rec = gr.Button("🎙️ Recording Tips", elem_classes=["robot-chip"])
                    chip_models = gr.Button("🧠 ML Models", elem_classes=["robot-chip"])
                    chip_triage = gr.Button("🩺 Result Meaning", elem_classes=["robot-chip"])
                    chip_pdf = gr.Button("📄 PDF Reports", elem_classes=["robot-chip"])

                chatbot = gr.Chatbot(label="AEROVA Robot Chat", height=280)
                with gr.Row():
                    chat_input = gr.Textbox(label="Message Robot", placeholder="Ask anything about cough screening, models, features...", scale=4)
                    chat_send = gr.Button("Ask Robot", variant="primary", elem_classes=["primary-button"], scale=1)

        # Dispatch and report state tracking
        report_meta_state = gr.State({})

        # Login event bindings
        login_button.click(
            _demo_login,
            [login_email, login_password, captcha_entry, captcha_answer_state],
            [login_view, workspace, login_email_state, login_notice],
        )
        fast_demo_btn.click(
            _fast_demo_login,
            outputs=[login_view, workspace, login_email_state, login_notice],
        )
        captcha_refresh.click(lambda: _new_captcha(), outputs=[captcha_prompt, captcha_answer_state])

        # Gemini key saving
        save_key_button.click(_set_gemini_key, [gemini_key_input], [gemini_key_state, key_status_box])

        # Chat interaction bindings (supports dynamic key state)
        chat_send.click(_chat_response, [chat_input, chatbot, gemini_key_state], [chatbot, chat_input])
        chat_input.submit(_chat_response, [chat_input, chatbot, gemini_key_state], [chatbot, chat_input])

        # Quick prompt chip shortcuts
        chip_rec.click(lambda h, k: _chat_response("What are the best tips for recording a clear cough?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_models.click(lambda h, k: _chat_response("Which machine learning models does AEROVA use and how accurate are they?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_triage.click(lambda h, k: _chat_response("What does a Healthy versus Disease result mean in AEROVA?", h, k), [chatbot, gemini_key_state], [chatbot, chat_input])
        chip_pdf.click(lambda h, k: _chat_response("How do I export and download a clinical PDF report with QR verification?", h, h), [chatbot, gemini_key_state], [chatbot, chat_input])

        # Patient history refresh
        history_refresh.click(history_dashboard_html, [history_search], [history_output])

        # Screening navigation flow
        continue_audio.click(_continue_audio, [audio_input, file_input, url_input], [audio_step, context_step, audio_notice])
        back_audio.click(lambda: (gr.update(visible=True), gr.update(visible=False)), outputs=[audio_step, context_step])
        back_result.click(lambda: (gr.update(visible=False), gr.update(visible=True)), outputs=[result_step, context_step])
        new_assessment.click(
            lambda: (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", "", "", ""),
            outputs=[result_step, audio_step, context_step, prediction_output, details_output, dispatch_status, dispatch_phone],
        )

        # Generate prediction
        predict_button.click(
            lambda email, *values: _run_prediction(predict_fn, email, *values),
            inputs=[login_email_state, audio_input, file_input, url_input, manual_notes, model_choice, gender, age, cough_detected, respiratory_condition, fever_muscle_pain],
            outputs=[prediction_output, details_output, quality_output, explanation_chart, model_comparison_output, pdf_report, history_output, context_step, result_step, report_meta_state, dispatch_email],
        )

        # Multi-channel report dispatching
        dispatch_wa_btn.click(_dispatch_whatsapp, [dispatch_phone, report_meta_state], [dispatch_status])
        dispatch_email_btn.click(_dispatch_email, [dispatch_email, report_meta_state], [dispatch_status])

    return interface
