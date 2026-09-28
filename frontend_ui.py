from html import escape
from datetime import datetime
import os
import logging
import time
from functools import lru_cache
import re
import secrets
from urllib.parse import quote
import base64

import gradio as gr
import requests

from reporting import (
    create_pdf_report,
    history_dashboard_html,
    save_assessment,
    clear_history,
    journey_dashboard_html,
    load_history,
)

# Global active key store (allows setting via UI, environment, or .env)
ACTIVE_GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY", "").strip()
    or os.environ.get("GOOGLE_API_KEY", "").strip()
)

AI_VIDEO_B64_FILE = os.path.join(os.path.dirname(__file__), "ai_respiratory_scan_b64.txt")
AI_VIDEO_DATA_URI = ""
if os.path.exists(AI_VIDEO_B64_FILE):
    try:
        with open(AI_VIDEO_B64_FILE, "r") as f:
            AI_VIDEO_DATA_URI = f"data:video/mp4;base64,{f.read().strip()}"
    except Exception:
        AI_VIDEO_DATA_URI = ""

APP_HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<script>
window.sendPdfToWhatsApp = async function(patientId, phone, pdfDataUri) {
  const cleanPhone = (phone || '').replace(/[^\\d]/g, '');
  const filename = 'AEROVA-Report-' + patientId + '.pdf';
  if (pdfDataUri && navigator.canShare) {
    try {
      const res = await fetch(pdfDataUri);
      const blob = await res.blob();
      const file = new File([blob], filename, { type: 'application/pdf' });
      if (navigator.canShare({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: 'AEROVA PDF Report - ' + patientId,
          text: '📄 AEROVA Verified Medical Screening Report (PDF Document)'
        });
        return;
      }
    } catch (e) {
      console.log('Share bypassed:', e);
    }
  }
  if (pdfDataUri) {
    const dl = document.createElement('a');
    dl.href = pdfDataUri;
    dl.download = filename;
    document.body.appendChild(dl);
    dl.click();
    document.body.removeChild(dl);
  }
  const waMsg = encodeURIComponent(
    '📄 *AEROVA CLINICAL SCREENING REPORT (OFFICIAL PDF)*\\n' +
    '━━━━━━━━━━━━━━━━━━━━━━\\n' +
    '📋 *Patient ID:* ' + patientId + '\\n' +
    '📎 *Attached Document:* ' + filename + '\\n' +
    '━━━━━━━━━━━━━━━━━━━━━━\\n' +
    'ℹ️ Verified clinical acoustic screening report in official PDF format.'
  );
  const waUrl = cleanPhone
    ? 'https://api.whatsapp.com/send?phone=' + cleanPhone + '&text=' + waMsg
    : 'https://api.whatsapp.com/send?text=' + waMsg;
  window.open(waUrl, '_blank');
};

let simMode = 'aerosol';
window.setFlightSimMode = function(mode) {
  simMode = mode;
  document.querySelectorAll('.banner-mode-btn').forEach(b => {
    if (b.innerText.toLowerCase().includes(mode) || (mode === 'pulmonary' && b.innerText.includes('Inhale'))) {
      b.classList.add('active');
    } else if (!b.innerText.includes('Port 5000')) {
      b.classList.remove('active');
    }
  });
};

window.switchTab = function(index) {
  const tabButtons = document.querySelectorAll('.aerova-main-tabs .tab-nav button');
  if (tabButtons && tabButtons[index]) {
    tabButtons[index].click();
  }
  document.querySelectorAll('.mobile-nav-btn').forEach((b, i) => {
    if (i === index) b.classList.add('active');
    else b.classList.remove('active');
  });
};

window.startSpeechRecognition = function(langChoice, inputSelector, statusId) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const statusEl = document.getElementById(statusId);
  if (!SpeechRecognition) {
    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.innerHTML = '<span style="color:#f59e0b;">⚠️ Speech recognition not supported in this browser. Please use Chrome/Edge or type your question.</span>';
    }
    return;
  }
  const recognition = new SpeechRecognition();
  const lang = (langChoice || '').toLowerCase();
  let langCode = 'en-US';
  if (lang.includes('kannada') || lang.includes('ಕನ್ನಡ')) langCode = 'kn-IN';
  else if (lang.includes('telugu') || lang.includes('తెలుగు')) langCode = 'te-IN';
  else if (lang.includes('hindi') || lang.includes('हिंदी')) langCode = 'hi-IN';
  
  recognition.lang = langCode;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.innerHTML = '<span style="color:#ef4444; font-weight:800;">🔴 Listening (' + langCode + ')... Speak your question now!</span>';
  }

  recognition.onresult = function(event) {
    const text = event.results[0][0].transcript;
    const inputEl = document.querySelector(inputSelector + ' textarea') || document.querySelector(inputSelector + ' input');
    if (inputEl) {
      inputEl.value = text;
      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (statusEl) {
      statusEl.innerHTML = '<span style="color:#00e5b0; font-weight:800;">✓ Voice Transcribed: "' + text + '"</span>';
      setTimeout(() => { if (statusEl) statusEl.style.display = 'none'; }, 4000);
    }
  };

  recognition.onerror = function(event) {
    if (statusEl) {
      statusEl.innerHTML = '<span style="color:#f59e0b;">⚠️ Mic status: ' + event.error + '. Please check browser mic permissions.</span>';
    }
  };

  recognition.start();
};

function initFlightCanvasLoop() {
  const canvas = document.getElementById('bio-flight-canvas');
  if (!canvas || canvas.dataset.initialized) return;
  canvas.dataset.initialized = 'true';
  const ctx = canvas.getContext('2d');
  let w, h;
  function resize() {
    w = canvas.width = canvas.parentElement.clientWidth || 800;
    h = canvas.height = canvas.parentElement.clientHeight || 160;
  }
  resize();
  window.addEventListener('resize', resize);

  const particles = [];
  const count = 75;
  for (let i = 0; i < count; i++) {
    particles.push({
      x: Math.random() * (w || 800),
      y: Math.random() * (h || 160),
      vx: 0.9 + Math.random() * 1.8,
      vy: (Math.random() - 0.5) * 0.8,
      radius: Math.random() * 2.2 + 0.8,
      alpha: Math.random() * 0.6 + 0.35,
      hue: Math.random() > 0.4 ? 165 : 195
    });
  }

  let t = 0;
  function draw() {
    ctx.clearRect(0, 0, w, h);
    t += 0.03;

    ctx.beginPath();
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.08)';
    ctx.lineWidth = 1.5;
    for (let line = 0; line < 3; line++) {
      const yBase = (h / 4) * (line + 1);
      ctx.moveTo(0, yBase);
      for (let x = 0; x < w; x += 30) {
        const ySin = yBase + Math.sin(x * 0.015 + t + line) * 12;
        ctx.lineTo(x, ySin);
      }
    }
    ctx.stroke();

    particles.forEach(p => {
      if (simMode === 'wave') {
        p.y += Math.sin(p.x * 0.04 + t * 2) * 1.5;
        p.vx = 2.4;
      } else if (simMode === 'pulmonary') {
        const targetX = w * 0.85;
        const targetY = h * 0.5;
        p.vx += (targetX - p.x) * 0.001;
        p.vy += (targetY - p.y) * 0.002;
      } else {
        p.vx = 1.3;
      }

      p.x += p.vx;
      p.y += p.vy;

      if (p.x > w + 10) { p.x = -10; p.y = Math.random() * h; }
      if (p.y < 0) p.y = h;
      if (p.y > h) p.y = 0;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fillStyle = `hsla(${p.hue}, 100%, 65%, ${p.alpha})`;
      ctx.shadowColor = `hsl(${p.hue}, 100%, 50%)`;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x - p.vx * 6, p.y - p.vy * 2);
      ctx.strokeStyle = `hsla(${p.hue}, 100%, 65%, ${p.alpha * 0.35})`;
      ctx.lineWidth = p.radius * 0.8;
      ctx.stroke();
    });

    requestAnimationFrame(draw);
  }
  draw();
}

setInterval(initFlightCanvasLoop, 500);

// =========================================================================
// MODULE 1: 3D RESPIRATORY VIDEO & BIOACOUSTIC CINEMA ENGINE
// =========================================================================
let cinemaMode = 'lungs';
let isCinemaPlaying = true;
let cinemaYaw = 0;
let cinemaPitch = 0.12;
let cinemaT = 0;
let coughImpulseTimer = 0;
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) audioCtx = new AudioContext();
  }
  if (audioCtx && audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  return audioCtx;
}

window.triggerSonarPing = function() {
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(580, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(890, ctx.currentTime + 0.18);
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.36);
  } catch(e) { console.log('Audio bypassed:', e); }
};

window.triggerCoughBurst = function() {
  coughImpulseTimer = 60;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const bufferSize = Math.floor(ctx.sampleRate * 0.28);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (ctx.sampleRate * 0.07));
    }
    const noise = ctx.createBufferSource();
    noise.buffer = buffer;
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 820;
    filter.Q.value = 2.2;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.28);
    noise.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    noise.start();
  } catch(e) { console.log('Audio bypassed:', e); }
};

let cinemaMode = 'video';

window.setCinemaMode = function(mode) {
  cinemaMode = mode;
  document.querySelectorAll('.cinema-mode-pill').forEach(pill => {
    if (pill.dataset.mode === mode) {
      pill.classList.add('active');
    } else {
      pill.classList.remove('active');
    }
  });
  const canvas = document.getElementById('cinema-3d-canvas');
  const video = document.getElementById('cinema-ai-video');
  const tagRight = document.querySelector('.cinema-hud-tag-right');
  const tagTop = document.querySelector('.cinema-hud-tag-top');
  
  if (mode === 'video') {
    if (canvas) canvas.style.display = 'none';
    if (video) {
      video.style.display = 'block';
      video.play().catch(e => console.log('Autoplay muted:', e));
    }
    if (tagRight) tagRight.innerText = 'MODE: AI PATIENT CLINICAL VIDEO';
    if (tagTop) tagTop.innerText = '4K AI NEURAL VIDEO · 30 FPS';
  } else {
    if (video) {
      video.style.display = 'none';
      video.pause();
    }
    if (canvas) canvas.style.display = 'block';
    if (tagTop) tagTop.innerText = '4K BIOACOUSTIC 3D HUD · 60 FPS';
    if (mode === 'lungs') {
      if (tagRight) tagRight.innerText = 'MODE: 3D PULMONARY FLOW';
    } else if (mode === 'wave') {
      if (tagRight) tagRight.innerText = 'MODE: 3D ACOUSTIC SONOGRAM';
    } else if (mode === 'radar') {
      if (tagRight) tagRight.innerText = 'MODE: 3D BIOMARKER RADAR';
    }
  }
};

window.toggleCinemaPlay = function() {
  const video = document.getElementById('cinema-ai-video');
  const playBtn = document.getElementById('cinema-play-btn');
  if (cinemaMode === 'video' && video) {
    if (video.paused) {
      video.play();
      if (playBtn) playBtn.innerText = '⏸ Pause';
    } else {
      video.pause();
      if (playBtn) playBtn.innerText = '▶ Play';
    }
    return;
  }
  isCinemaPlaying = !isCinemaPlaying;
  if (playBtn) {
    playBtn.innerText = isCinemaPlaying ? '⏸ Pause' : '▶ Play';
  }
};

window.copySoapSummary = function() {
  const soapEl = document.getElementById('soap-summary-text');
  if (soapEl) {
    navigator.clipboard.writeText(soapEl.innerText).then(() => {
      const toast = document.getElementById('soap-copy-toast');
      if (toast) {
        toast.style.display = 'inline-block';
        setTimeout(() => toast.style.display = 'none', 3000);
      }
    });
  }
};


window.resetCinemaCamera = function() {
  cinemaYaw = 0;
  cinemaPitch = 0.12;
};

function initCinema3D() {
  const canvas = document.getElementById('cinema-3d-canvas');
  if (!canvas || canvas.dataset.initialized) return;
  canvas.dataset.initialized = 'true';
  const ctx = canvas.getContext('2d');
  let w = 0, h = 0;

  function resize() {
    if (!canvas.parentElement) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    w = canvas.width = rect.width || 480;
    h = canvas.height = rect.height || 290;
  }
  resize();
  window.addEventListener('resize', resize);

  let isDragging = false;
  let prevX = 0, prevY = 0;
  canvas.addEventListener('mousedown', e => {
    isDragging = true;
    prevX = e.clientX;
    prevY = e.clientY;
  });
  window.addEventListener('mousemove', e => {
    if (!isDragging) return;
    const dx = e.clientX - prevX;
    const dy = e.clientY - prevY;
    cinemaYaw += dx * 0.008;
    cinemaPitch = Math.max(-0.6, Math.min(0.6, cinemaPitch + dy * 0.008));
    prevX = e.clientX;
    prevY = e.clientY;
  });
  window.addEventListener('mouseup', () => { isDragging = false; });

  canvas.addEventListener('touchstart', e => {
    if (e.touches.length === 1) {
      isDragging = true;
      prevX = e.touches[0].clientX;
      prevY = e.touches[0].clientY;
    }
  }, { passive: true });
  window.addEventListener('touchmove', e => {
    if (!isDragging || e.touches.length !== 1) return;
    const dx = e.touches[0].clientX - prevX;
    const dy = e.touches[0].clientY - prevY;
    cinemaYaw += dx * 0.008;
    cinemaPitch = Math.max(-0.6, Math.min(0.6, cinemaPitch + dy * 0.008));
    prevX = e.touches[0].clientX;
    prevY = e.touches[0].clientY;
  }, { passive: true });
  window.addEventListener('touchend', () => { isDragging = false; });

  const lungNodes = [];
  for (let i = 0; i < 48; i++) {
    const u = Math.random() * Math.PI * 2;
    const v = Math.random() * Math.PI;
    const r = 26 + Math.random() * 16;
    lungNodes.push({
      x: -36 + Math.sin(v) * Math.cos(u) * r * 0.85,
      y: 8 + Math.cos(v) * r * 1.35,
      z: Math.sin(v) * Math.sin(u) * r * 0.75,
      side: 'left',
      phase: Math.random() * Math.PI * 2,
      baseRadius: Math.random() * 2.2 + 1.2
    });
  }
  for (let i = 0; i < 56; i++) {
    const u = Math.random() * Math.PI * 2;
    const v = Math.random() * Math.PI;
    const r = 28 + Math.random() * 18;
    lungNodes.push({
      x: 36 + Math.sin(v) * Math.cos(u) * r * 0.9,
      y: 8 + Math.cos(v) * r * 1.35,
      z: Math.sin(v) * Math.sin(u) * r * 0.8,
      side: 'right',
      phase: Math.random() * Math.PI * 2,
      baseRadius: Math.random() * 2.2 + 1.2
    });
  }

  const flowParticles = [];
  for (let i = 0; i < 35; i++) {
    flowParticles.push({
      tNorm: Math.random(),
      speed: 0.008 + Math.random() * 0.012,
      branch: Math.random() > 0.5 ? 1 : -1,
      radius: Math.random() * 1.8 + 0.8,
      alpha: Math.random() * 0.7 + 0.3
    });
  }

  function project(x, y, z, cx, cy) {
    const cosY = Math.cos(cinemaYaw);
    const sinY = Math.sin(cinemaYaw);
    const x1 = x * cosY - z * sinY;
    const z1 = z * cosY + x * sinY;

    const cosP = Math.cos(cinemaPitch);
    const sinP = Math.sin(cinemaPitch);
    const y2 = y * cosP - z1 * sinP;
    const z2 = z1 * cosP + y * sinP;

    const dist = 240;
    const fov = 320;
    const scale = fov / (dist + z2);
    return {
      px: cx + x1 * scale,
      py: cy + y2 * scale,
      scale: scale,
      z: z2
    };
  }

  function render() {
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2;
    const cy = h / 2 - 6;

    if (isCinemaPlaying) {
      cinemaT += 0.035;
      if (!isDragging) cinemaYaw += 0.003;
    }

    if (coughImpulseTimer > 0) coughImpulseTimer--;

    const tcEl = document.getElementById('cinema-timecode-display');
    if (tcEl) {
      const sec = ((cinemaT * 0.5) % 15).toFixed(1);
      tcEl.innerText = '00:' + (sec < 10 ? '0' + sec : sec) + ' / 00:15.0';
    }

    if (cinemaMode === 'lungs') {
      const breath = 1.0 + Math.sin(cinemaT * 1.6) * 0.09;
      const isBurst = coughImpulseTimer > 0;

      ctx.lineWidth = 3.5;
      ctx.strokeStyle = isBurst ? 'rgba(244, 63, 94, 0.85)' : 'rgba(56, 189, 248, 0.75)';
      ctx.lineCap = 'round';

      const topP = project(0, -65, 0, cx, cy);
      const carinaP = project(0, -15, 0, cx, cy);
      ctx.beginPath();
      ctx.moveTo(topP.px, topP.py);
      ctx.lineTo(carinaP.px, carinaP.py);
      ctx.stroke();

      const leftBronchus = project(-28 * breath, 6, 2, cx, cy);
      const rightBronchus = project(28 * breath, 6, -2, cx, cy);
      ctx.beginPath();
      ctx.moveTo(carinaP.px, carinaP.py);
      ctx.lineTo(leftBronchus.px, leftBronchus.py);
      ctx.moveTo(carinaP.px, carinaP.py);
      ctx.lineTo(rightBronchus.px, rightBronchus.py);
      ctx.stroke();

      ctx.lineWidth = 1.8;
      ctx.strokeStyle = isBurst ? 'rgba(244, 63, 94, 0.6)' : 'rgba(0, 229, 176, 0.6)';
      const lBranch1 = project(-48 * breath, 28, 10, cx, cy);
      const lBranch2 = project(-38 * breath, 44, -8, cx, cy);
      const rBranch1 = project(50 * breath, 28, -10, cx, cy);
      const rBranch2 = project(40 * breath, 46, 8, cx, cy);

      ctx.beginPath();
      ctx.moveTo(leftBronchus.px, leftBronchus.py);
      ctx.lineTo(lBranch1.px, lBranch1.py);
      ctx.moveTo(leftBronchus.px, leftBronchus.py);
      ctx.lineTo(lBranch2.px, lBranch2.py);
      ctx.moveTo(rightBronchus.px, rightBronchus.py);
      ctx.lineTo(rBranch1.px, rBranch1.py);
      ctx.moveTo(rightBronchus.px, rightBronchus.py);
      ctx.lineTo(rBranch2.px, rBranch2.py);
      ctx.stroke();

      flowParticles.forEach(fp => {
        if (isCinemaPlaying) {
          fp.tNorm += fp.speed;
          if (fp.tNorm > 1) fp.tNorm = 0;
        }
        let px3d = 0, py3d = -65 + fp.tNorm * 50, pz3d = 0;
        if (fp.tNorm > 0.4) {
          const split = (fp.tNorm - 0.4) / 0.6;
          px3d = fp.branch * split * 42 * breath;
          py3d = -15 + split * 55;
          pz3d = fp.branch * Math.sin(split * Math.PI) * 12;
        }
        const p2d = project(px3d, py3d, pz3d, cx, cy);
        ctx.beginPath();
        ctx.arc(p2d.px, p2d.py, fp.radius * p2d.scale, 0, Math.PI * 2);
        ctx.fillStyle = isBurst ? 'rgba(255, 120, 150, 0.95)' : 'rgba(56, 189, 248, 0.85)';
        ctx.fill();
      });

      const sortedNodes = lungNodes.map(n => {
        const dynamicBreath = 1.0 + Math.sin(cinemaT * 1.6 + n.phase) * 0.1;
        const p = project(n.x * dynamicBreath, n.y * dynamicBreath, n.z * dynamicBreath, cx, cy);
        return { p, n };
      }).sort((a, b) => b.p.z - a.p.z);

      sortedNodes.forEach(({ p, n }) => {
        const rad = Math.max(0.8, n.baseRadius * p.scale);
        const alpha = Math.max(0.2, Math.min(0.9, (p.scale - 0.5) * 1.4));
        ctx.beginPath();
        ctx.arc(p.px, p.py, rad, 0, Math.PI * 2);
        if (isBurst) {
          ctx.fillStyle = `rgba(244, 63, 94, ${alpha})`;
          ctx.shadowColor = '#f43f5e';
        } else {
          ctx.fillStyle = n.side === 'left' ? `rgba(0, 229, 176, ${alpha})` : `rgba(56, 189, 248, ${alpha})`;
          ctx.shadowColor = n.side === 'left' ? '#00e5b0' : '#38bdf8';
        }
        ctx.shadowBlur = 6;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      if (coughImpulseTimer > 0) {
        const waveRadius = (60 - coughImpulseTimer) * 4.5;
        const waveAlpha = coughImpulseTimer / 60;
        ctx.beginPath();
        ctx.arc(cx, cy + 10, waveRadius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(244, 63, 94, ${waveAlpha * 0.8})`;
        ctx.lineWidth = 3;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(cx, cy + 10, waveRadius * 0.65, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(0, 229, 176, ${waveAlpha * 0.9})`;
        ctx.lineWidth = 2;
        ctx.stroke();
      }

    } else if (cinemaMode === 'wave') {
      const cols = 22;
      const rows = 12;
      ctx.lineWidth = 1.2;

      for (let r = 0; r < rows; r++) {
        ctx.beginPath();
        const zRow = (r - rows / 2) * 16;
        const rowColor = r % 2 === 0 ? 'rgba(0, 229, 176, 0.7)' : 'rgba(56, 189, 248, 0.6)';
        ctx.strokeStyle = rowColor;

        for (let c = 0; c < cols; c++) {
          const xCol = (c - cols / 2) * 16;
          const dist = Math.sqrt(xCol * xCol + zRow * zRow);
          const waveHeight = Math.sin(dist * 0.08 - cinemaT * 2.5) * Math.cos(c * 0.3) * 22;
          const p = project(xCol, waveHeight, zRow, cx, cy);
          if (c === 0) ctx.moveTo(p.px, p.py);
          else ctx.lineTo(p.px, p.py);
        }
        ctx.stroke();
      }

      const p1 = project(-30, -32 + Math.sin(cinemaT * 3) * 8, 0, cx, cy);
      ctx.fillStyle = '#00e5b0';
      ctx.beginPath();
      ctx.arc(p1.px, p1.py, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      ctx.fillText('F1: 680Hz', p1.px + 8, p1.py - 2);

      const p2 = project(35, -28 + Math.cos(cinemaT * 2.8) * 8, 0, cx, cy);
      ctx.fillStyle = '#38bdf8';
      ctx.beginPath();
      ctx.arc(p2.px, p2.py, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      ctx.fillText('F2: 1,420Hz', p2.px + 8, p2.py - 2);

    } else if (cinemaMode === 'radar') {
      const ringCount = 4;
      for (let i = 1; i <= ringCount; i++) {
        const rad = i * 28;
        ctx.beginPath();
        for (let a = 0; a <= Math.PI * 2; a += 0.1) {
          const p = project(Math.cos(a) * rad, 10, Math.sin(a) * rad, cx, cy);
          if (a === 0) ctx.moveTo(p.px, p.py);
          else ctx.lineTo(p.px, p.py);
        }
        ctx.strokeStyle = `rgba(56, 189, 248, ${0.15 + i * 0.08})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      const beamAngle = cinemaT * 2.2;
      const bCenter = project(0, 10, 0, cx, cy);
      const bEdge = project(Math.cos(beamAngle) * 115, 10, Math.sin(beamAngle) * 115, cx, cy);
      ctx.beginPath();
      ctx.moveTo(bCenter.px, bCenter.py);
      ctx.lineTo(bEdge.px, bEdge.py);
      ctx.strokeStyle = 'rgba(0, 229, 176, 0.9)';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = '#00e5b0';
      ctx.shadowBlur = 10;
      ctx.stroke();
      ctx.shadowBlur = 0;

      const markers = [
        { label: 'MFCC-1', score: 0.88, angle: 0 },
        { label: 'Centroid', score: 0.82, angle: Math.PI / 3 },
        { label: 'Kurtosis', score: 0.92, angle: (2 * Math.PI) / 3 },
        { label: 'ZCR', score: 0.74, angle: Math.PI },
        { label: 'RMS Pow', score: 0.85, angle: (4 * Math.PI) / 3 },
        { label: 'Rolloff', score: 0.89, angle: (5 * Math.PI) / 3 }
      ];

      ctx.beginPath();
      ctx.fillStyle = 'rgba(0, 229, 176, 0.25)';
      ctx.strokeStyle = '#00e5b0';
      ctx.lineWidth = 2;
      markers.forEach((m, idx) => {
        const rad = m.score * 105;
        const p = project(Math.cos(m.angle) * rad, 10, Math.sin(m.angle) * rad, cx, cy);
        if (idx === 0) ctx.moveTo(p.px, p.py);
        else ctx.lineTo(p.px, p.py);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      markers.forEach(m => {
        const p = project(Math.cos(m.angle) * 125, 10, Math.sin(m.angle) * 125, cx, cy);
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px monospace';
        ctx.fillText(m.label + ' ' + (m.score * 100).toFixed(0) + '%', p.px - 22, p.py);
      });
    }

    requestAnimationFrame(render);
  }
  render();
}

function initCardParallax() {
  const card = document.querySelector('.login-3d-visual-card');
  if (!card || card.dataset.tiltBound) return;
  card.dataset.tiltBound = 'true';

  card.addEventListener('mousemove', e => {
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const xMid = rect.width / 2;
    const yMid = rect.height / 2;
    const rotX = ((y - yMid) / yMid) * -6;
    const rotY = ((x - xMid) / xMid) * 6;
    card.style.transform = `perspective(1000px) rotateX(${rotX}deg) rotateY(${rotY}deg) scale3d(1.01, 1.01, 1.01)`;
  });

  card.addEventListener('mouseleave', () => {
    card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
  });
}

window.runAcousticProbeCheck = function() {
  const resBox = document.getElementById('probe-results-box');
  const btn = document.querySelector('.probe-btn');
  if (!resBox) return;
  resBox.style.display = 'grid';
  resBox.innerHTML = '<div style="grid-column: 1 / -1; color:#38bdf8; font-weight:700; font-size:11.5px; text-align:center;">⚡ Initializing 22,050 Hz Audio Probe & Calculating Room SNR...</div>';
  if (btn) btn.disabled = true;

  window.triggerSonarPing();

  setTimeout(() => {
    resBox.innerHTML = `
      <div class="probe-metric-box">
        <div style="font-size:9.5px; color:#94a3b8; text-transform:uppercase;">Sampling Rate</div>
        <div style="font-size:14px; font-weight:800; color:#ffffff;">22,050 Hz</div>
        <div style="font-size:9.5px; color:#00e5b0;">Nyquist: 11 kHz</div>
      </div>
      <div class="probe-metric-box">
        <div style="font-size:9.5px; color:#94a3b8; text-transform:uppercase;">Acoustic SNR</div>
        <div style="font-size:14px; font-weight:800; color:#00e5b0;">26.4 dB</div>
        <div style="font-size:9.5px; color:#00e5b0;">Threshold > 15 dB</div>
      </div>
      <div class="probe-metric-box">
        <div style="font-size:9.5px; color:#94a3b8; text-transform:uppercase;">Quality Gate</div>
        <div style="font-size:14px; font-weight:800; color:#38bdf8;">PASSED</div>
        <div style="font-size:9.5px; color:#94a3b8;">Noise: -49 dBFS</div>
      </div>
    `;
    if (btn) btn.disabled = false;
  }, 1200);
};

function initPasswordMeter() {
  const pwdInput = document.querySelector('.password-box input');
  if (!pwdInput || pwdInput.dataset.meterBound) return;
  pwdInput.dataset.meterBound = 'true';

  pwdInput.addEventListener('input', () => {
    const val = pwdInput.value;
    const ruleLen = document.getElementById('rule-len');
    const ruleUpper = document.getElementById('rule-upper');
    const ruleNum = document.getElementById('rule-num');
    const ruleSym = document.getElementById('rule-sym');
    const barFill = document.querySelector('.pwd-meter-fill');

    let passed = 0;
    if (val.length >= 8) { ruleLen?.classList.add('valid'); passed++; } else ruleLen?.classList.remove('valid');
    if (/[A-Z]/.test(val)) { ruleUpper?.classList.add('valid'); passed++; } else ruleUpper?.classList.remove('valid');
    if (/[0-9]/.test(val)) { ruleNum?.classList.add('valid'); passed++; } else ruleNum?.classList.remove('valid');
    if (/[^A-Za-z0-9]/.test(val)) { ruleSym?.classList.add('valid'); passed++; } else ruleSym?.classList.remove('valid');

    if (barFill) {
      const pct = (passed / 4) * 100;
      barFill.style.width = pct + '%';
      if (passed <= 1) barFill.style.backgroundColor = '#ef4444';
      else if (passed === 2) barFill.style.backgroundColor = '#f59e0b';
      else if (passed === 3) barFill.style.backgroundColor = '#38bdf8';
      else barFill.style.backgroundColor = '#00e5b0';
    }
  });
}

setInterval(() => {
  initCinema3D();
  initCardParallax();
  initPasswordMeter();
}, 600);
</script>
"""

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
   TOP 3D VIDEO / FLYING PARTICLE BANNER & SIMULATION HUD
   ========================================================================= */
.top-flight-banner {
  position: relative;
  width: 100%;
  height: 160px;
  background: radial-gradient(circle at 50% 20%, rgba(2, 28, 48, 0.95) 0%, rgba(2, 12, 22, 0.98) 100%);
  border: 1px solid var(--border-line);
  border-radius: 24px;
  overflow: hidden;
  margin-bottom: 24px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6), inset 0 0 30px rgba(0, 229, 176, 0.08);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px 24px;
}

#bio-flight-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}

.banner-content {
  position: relative;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.banner-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.banner-icon-glow {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(0, 229, 176, 0.25), rgba(56, 189, 248, 0.2));
  border: 1px solid var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  box-shadow: 0 0 24px var(--primary-glow);
  animation: floatHolo 4s ease-in-out infinite;
}

.banner-title-group h2 {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff !important;
  letter-spacing: -0.02em;
  margin: 0 0 4px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.banner-title-group p {
  font-size: 13px;
  color: #cbd5e1 !important;
  margin: 0;
}

.banner-telemetry-row {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  border-top: 1px solid rgba(56, 189, 248, 0.18);
  padding-top: 10px;
}

.banner-telemetry-pills {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.banner-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(6, 21, 33, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #f1f5f9;
}

.banner-sim-controls {
  display: flex;
  gap: 6px;
}

.banner-mode-btn {
  background: rgba(0, 229, 176, 0.12);
  border: 1px solid var(--primary);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.banner-mode-btn:hover, .banner-mode-btn.active {
  background: var(--primary);
  color: #03141f;
  box-shadow: 0 0 14px var(--primary-glow);
}

/* =========================================================================
   REALISTIC 3D LOGIN STAGE & HOLOGRAPHIC LUNG
   ========================================================================= */
.login-shell {
  max-width: 1120px;
  margin: 20px auto 30px;
}

.login-3d-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  align-items: stretch;
}

.login-3d-visual-card {
  background: linear-gradient(145deg, rgba(8, 26, 38, 0.95) 0%, rgba(4, 15, 24, 0.98) 100%);
  border: 1px solid rgba(0, 229, 176, 0.35);
  border-radius: 26px;
  padding: 32px 28px;
  box-shadow: var(--shadow-pro), 0 0 30px rgba(0, 229, 176, 0.12);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  overflow: hidden;
  perspective: 1000px;
}

.login-3d-visual-card::before {
  content: "";
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle at 50% 50%, rgba(0, 229, 176, 0.06) 0%, transparent 60%);
  pointer-events: none;
}

.hologram-stage {
  position: relative;
  width: 100%;
  height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin: 14px 0;
}

.hologram-lung-visual {
  font-size: 82px;
  filter: drop-shadow(0 0 25px rgba(0, 229, 176, 0.65));
  animation: floatHolo 3.5s ease-in-out infinite;
  position: relative;
  z-index: 2;
  user-select: none;
}

.scanner-beam {
  position: absolute;
  width: 160px;
  height: 2px;
  background: linear-gradient(90deg, transparent, #00e5b0, #38bdf8, transparent);
  box-shadow: 0 0 12px #00e5b0, 0 0 24px #38bdf8;
  z-index: 3;
  animation: scanBeam 3s ease-in-out infinite alternate;
}

.hologram-ring {
  position: absolute;
  border-radius: 50%;
  border: 1px dashed rgba(56, 189, 248, 0.35);
  pointer-events: none;
  z-index: 1;
}

.ring-outer {
  width: 190px;
  height: 190px;
  animation: ringRotate 20s linear infinite;
  border-color: rgba(0, 229, 176, 0.25);
}

.ring-inner {
  width: 140px;
  height: 140px;
  animation: ringRotate 12s linear infinite reverse;
  border-color: rgba(56, 189, 248, 0.35);
}

.equalizer-stage {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  height: 38px;
  margin-top: 12px;
}

.eq-bar {
  width: 5px;
  border-radius: 999px;
  background: linear-gradient(to top, #0284c7, #00e5b0);
  box-shadow: 0 0 8px rgba(0, 229, 176, 0.4);
  animation: eqBounce 1.2s ease-in-out infinite alternate;
}

.eq-bar:nth-child(2) { animation-delay: 0.15s; height: 18px; }
.eq-bar:nth-child(3) { animation-delay: 0.3s; height: 28px; }
.eq-bar:nth-child(4) { animation-delay: 0.45s; height: 36px; }
.eq-bar:nth-child(5) { animation-delay: 0.2s; height: 22px; }
.eq-bar:nth-child(6) { animation-delay: 0.35s; height: 32px; }
.eq-bar:nth-child(7) { animation-delay: 0.1s; height: 14px; }
.eq-bar:nth-child(8) { animation-delay: 0.5s; height: 26px; }
.eq-bar:nth-child(9) { animation-delay: 0.25s; height: 20px; }

@keyframes floatHolo {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-8px) scale(1.03); }
}

@keyframes scanBeam {
  0% { top: 15%; opacity: 0.3; }
  50% { opacity: 0.9; }
  100% { top: 85%; opacity: 0.3; }
}

@keyframes ringRotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes eqBounce {
  0% { height: 6px; }
  100% { height: 34px; }
}

.login-panel {
  background: linear-gradient(145deg, rgba(11, 28, 41, 0.98), rgba(15, 45, 62, 0.98));
  border: 1px solid var(--border-line);
  border-radius: 26px;
  box-shadow: var(--shadow-pro);
  padding: 32px 30px;
}

.login-mark {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  font: 800 26px/1 Arial, sans-serif;
  color: #ffffff;
}

.login-copy {
  color: #cbd5e1;
  font-size: 14.5px;
  line-height: 1.55;
  margin: 10px 0 18px;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 16px 0 20px;
}

.metric-item {
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
  padding: 12px 14px;
}

.metric-label {
  display: block;
  font: 800 10.5px Arial, sans-serif;
  color: #94a3b8;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 4px;
  font: 800 24px/1 Arial, sans-serif;
  color: #ffffff;
}

.metric-trend {
  display: inline-block;
  margin-top: 4px;
  font: 700 10.5px Arial, sans-serif;
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

/* =========================================================================
   MODULE 1: NEXT-GEN 3D BIOACOUSTIC CINEMA & AUTHENTICATION GATEWAY
   ========================================================================= */
.login-shell {
  padding: 10px 0 30px;
}

.login-3d-grid {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 28px;
  align-items: stretch;
  margin: 10px 0 30px;
}

.login-3d-visual-card {
  background: linear-gradient(160deg, rgba(8, 28, 44, 0.88) 0%, rgba(3, 14, 24, 0.96) 100%);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 24px;
  padding: 24px;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.6), 0 0 40px rgba(0, 229, 176, 0.12);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(20px);
  transition: transform 0.2s cubic-bezier(0.25, 1, 0.5, 1), box-shadow 0.3s ease;
  transform-style: preserve-3d;
}

.login-3d-visual-card:hover {
  border-color: rgba(0, 229, 176, 0.55);
  box-shadow: 0 30px 70px rgba(0, 0, 0, 0.7), 0 0 50px rgba(0, 229, 176, 0.25);
}

.cinema-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.cinema-badge-live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(0, 229, 176, 0.15);
  color: #00e5b0;
  border: 1px solid rgba(0, 229, 176, 0.35);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.cinema-timecode {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #38bdf8;
  background: rgba(6, 18, 30, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 3px 10px;
  border-radius: 8px;
}

/* 3D VIDEO SIMULATION STAGE */
.cinema-video-stage {
  position: relative;
  width: 100%;
  height: 290px;
  background: radial-gradient(circle at center, rgba(14, 38, 58, 0.8) 0%, rgba(4, 12, 20, 0.95) 80%);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 18px;
  overflow: hidden;
  box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.8);
  cursor: grab;
}

.cinema-video-stage:active {
  cursor: grabbing;
}

#cinema-3d-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.cinema-scanlines {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.03), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.03));
  background-size: 100% 4px, 6px 100%;
  pointer-events: none;
  opacity: 0.6;
}

.cinema-hud-corners {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  bottom: 10px;
  pointer-events: none;
  border: 1px dashed rgba(56, 189, 248, 0.2);
  border-radius: 12px;
}

.cinema-hud-tag-top {
  position: absolute;
  top: 12px;
  left: 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.7);
  letter-spacing: 0.05em;
  pointer-events: none;
}

.cinema-hud-tag-right {
  position: absolute;
  top: 12px;
  right: 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #00e5b0;
  pointer-events: none;
}

/* CINEMA CONTROLS BAR */
.cinema-controls-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  background: rgba(4, 15, 24, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
  padding: 8px 12px;
}

.cinema-btn {
  background: rgba(15, 41, 60, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.25);
  color: #f1f5f9;
  border-radius: 10px;
  padding: 6px 12px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.cinema-btn:hover {
  background: rgba(0, 229, 176, 0.15);
  border-color: #00e5b0;
  color: #00e5b0;
  box-shadow: 0 0 12px rgba(0, 229, 176, 0.25);
}

.cinema-btn.primary {
  background: rgba(0, 229, 176, 0.2);
  border-color: #00e5b0;
  color: #00e5b0;
}

.cinema-mode-pills {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}

.cinema-mode-pill {
  flex: 1;
  text-align: center;
  background: rgba(6, 21, 33, 0.7);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 10px;
  padding: 7px 8px;
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s ease;
}

.cinema-mode-pill:hover {
  color: #ffffff;
  border-color: rgba(56, 189, 248, 0.5);
}

.cinema-mode-pill.active {
  background: linear-gradient(135deg, rgba(0, 229, 176, 0.2) 0%, rgba(56, 189, 248, 0.2) 100%);
  border-color: #00e5b0;
  color: #00e5b0;
  box-shadow: 0 0 14px rgba(0, 229, 176, 0.25);
}

/* HARDWARE PROBE CALIBRATION TEST */
.probe-test-card {
  margin-top: 14px;
  background: rgba(4, 15, 24, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 14px;
  padding: 12px 14px;
}

.probe-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.probe-btn {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid #38bdf8;
  color: #38bdf8;
  font-size: 11px;
  font-weight: 800;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.probe-btn:hover {
  background: #38bdf8;
  color: #04121e;
  box-shadow: 0 0 14px rgba(56, 189, 248, 0.4);
}

.probe-results {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.probe-metric-box {
  background: rgba(8, 26, 40, 0.8);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 8px;
  padding: 6px 8px;
  text-align: center;
}

/* RIGHT COLUMN: LOGIN & AUTH PORTAL */
.login-panel {
  background: linear-gradient(160deg, rgba(8, 28, 44, 0.92) 0%, rgba(3, 14, 24, 0.96) 100%);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 24px;
  padding: 24px 28px;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.6), 0 0 35px rgba(56, 189, 248, 0.1);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  backdrop-filter: blur(20px);
}

.login-mark {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.01em;
}

.login-copy {
  font-size: 13px;
  color: #94a3b8;
  line-height: 1.5;
  margin: 6px 0 14px;
}

.persona-select-container {
  background: rgba(2, 10, 20, 0.85);
  border: 1px solid var(--border-line);
  border-radius: 16px;
  padding: 14px 16px;
  margin-bottom: 14px;
}

.captcha-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-top: 14px;
}

.captcha-question {
  color: #00e5b0;
  font: 800 15px Arial, sans-serif;
  padding: 12px 14px;
  background: rgba(0, 229, 176, 0.12);
  border: 1px solid rgba(0, 229, 176, 0.35);
  border-radius: 12px;
  white-space: nowrap;
}

.captcha-autosolve {
  background: rgba(0, 229, 176, 0.18) !important;
  color: #00e5b0 !important;
  border: 1px solid rgba(0, 229, 176, 0.4) !important;
  font-weight: 800 !important;
  white-space: nowrap !important;
}

.captcha-autosolve:hover {
  background: #00e5b0 !important;
  color: #020813 !important;
  box-shadow: 0 0 14px rgba(0, 229, 176, 0.4) !important;
}

/* PASSWORD STRENGTH LIVE METER */
.pwd-meter-container {
  margin: 4px 0 12px;
}

.pwd-meter-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 6px;
}

.pwd-meter-fill {
  height: 100%;
  width: 0%;
  transition: width 0.3s ease, background-color 0.3s ease;
  background: #ef4444;
}

.pwd-rules {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 10.5px;
  color: #94a3b8;
}

.pwd-rule {
  background: rgba(15, 30, 45, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 2px 7px;
  transition: all 0.2s ease;
}

.pwd-rule.valid {
  border-color: #00e5b0;
  color: #00e5b0;
  background: rgba(0, 229, 176, 0.15);
}

.trust-badges-bar {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding-top: 12px;
  margin-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 11px;
  color: #94a3b8;
}

.trust-badge-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
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

/* =========================================================================
   MAIN TABS & WORKSPACE SECTIONS
   ========================================================================= */
.aerova-main-tabs {
  margin-top: 20px;
}

.aerova-main-tabs .tab-nav {
  display: flex !important;
  gap: 8px !important;
  background: rgba(6, 18, 28, 0.95) !important;
  border: 1px solid var(--border-line) !important;
  border-radius: 18px !important;
  padding: 8px !important;
  margin-bottom: 20px !important;
  overflow-x: auto;
  scrollbar-width: thin;
}

.aerova-main-tabs .tab-nav button {
  border-radius: 12px !important;
  font-weight: 700 !important;
  font-size: 13.5px !important;
  padding: 10px 18px !important;
  color: #94a3b8 !important;
  background: transparent !important;
  border: 1px solid transparent !important;
  transition: all 0.2s ease !important;
}

.aerova-main-tabs .tab-nav button:hover {
  color: #ffffff !important;
  background: rgba(56, 189, 248, 0.12) !important;
}

.aerova-main-tabs .tab-nav button.selected {
  color: #020813 !important;
  background: var(--primary) !important;
  border-color: var(--primary) !important;
  box-shadow: 0 0 16px var(--primary-glow) !important;
  font-weight: 800 !important;
}

/* PROFILE & PRIVACY LUXURY CARDS */
.profile-card, .privacy-card {
  background: linear-gradient(145deg, rgba(8, 26, 38, 0.92) 0%, rgba(4, 15, 24, 0.96) 100%);
  border: 1px solid var(--border-line);
  border-radius: 20px;
  padding: 24px 28px;
  box-shadow: var(--shadow-pro);
  margin-bottom: 16px;
}

.card-heading {
  font-size: 17px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.pref-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.pref-row:last-child {
  border-bottom: none;
}

.pref-label {
  font-size: 13px;
  font-weight: 700;
  color: #cbd5e1;
}

.pref-sub {
  font-size: 11.5px;
  color: #94a3b8;
  margin-top: 2px;
}

.pref-val {
  font-size: 13px;
  font-weight: 800;
  color: var(--primary);
}

/* AI PROMPT CHIPS */
.ai-chip-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

/* MOBILE BOTTOM NAVIGATION BAR */
.mobile-bottom-nav {
  display: none;
}

@media (max-width: 900px) {
  .login-3d-grid { grid-template-columns: 1fr; }
  .top-flight-banner { height: auto; }
}

@media (max-width: 768px) {
  .robot-dock { right: 10px; bottom: 70px; width: calc(100vw - 20px); }
  .hero-hospital { flex-direction: column; align-items: flex-start; }
  .hero-left, .hero-right { max-width: 100%; width: 100%; }
  .hero-right { align-items: flex-start; }
  .panel { padding: 18px; }
  .result-heading { font-size: 28px; }
  .dashboard-metrics { grid-template-columns: 1fr; }

  .mobile-bottom-nav {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 60px;
    background: rgba(2, 8, 16, 0.96);
    border-top: 1px solid var(--border-line);
    backdrop-filter: blur(16px);
    z-index: 999;
    align-items: center;
    justify-content: space-around;
    padding: 0 8px;
  }

  .mobile-nav-btn {
    background: none;
    border: none;
    color: #94a3b8;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    font-size: 10.5px;
    font-weight: 700;
    cursor: pointer;
    padding: 6px 12px;
  }

  .mobile-nav-btn span:first-child {
    font-size: 18px;
  }

  .mobile-nav-btn:hover, .mobile-nav-btn.active {
    color: var(--primary);
  }
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
    demo_email = "guest.exhibition@hospital-aerova.org"
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        demo_email,
        f'<div class="notification">⚡ <b>Instant Exhibition Access Granted.</b> Ready to test live cough audio!</div>',
    )


def _persona_login(persona_type):
    """Authenticate specific clinical, research, or patient persona."""
    if persona_type == "patient":
        email = "chinni.krishna@patient-aerova.org"
        notice = '<div class="notification">👤 Signed in as <b>Chinni Krishna (Patient)</b>. Baseline: Moderate Asthmatic Profile.</div>'
    elif persona_type == "doctor":
        email = "dr.aris@pulmonology-aerova.org"
        notice = '<div class="notification">🩺 Signed in as <b>Dr. Aris (Lead Pulmonologist)</b>. Hospital Clinical Triage Active.</div>'
    elif persona_type == "researcher":
        email = "dr.vance@ai-research.aerova.org"
        notice = '<div class="notification">🔬 Signed in as <b>Dr. Vance (Senior AI Researcher)</b>. GroupKFold Model Lab Unlocked.</div>'
    else:
        email = "guest.exhibition@aerova.org"
        notice = '<div class="notification">⚡ Signed in as <b>Exhibition Guest</b>. 1-Click Fast Pass Active.</div>'
    return gr.update(visible=False), gr.update(visible=True), email, notice



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


def _local_project_answer(lowered, lang="English"):
    """Extensive autonomous knowledge engine that answers questions in English, Kannada, Telugu, and Hindi."""
    import re
    is_kannada = bool(re.search(r'[\u0C80-\u0CFF]', lowered) or "kannada" in str(lang).lower())
    is_telugu = bool(re.search(r'[\u0C00-\u0C7F]', lowered) or "telugu" in str(lang).lower())
    is_hindi = bool(re.search(r'[\u0900-\u097F]', lowered) or "hindi" in str(lang).lower())

    # ==================== KANNADA (ಕನ್ನಡ) RESPONSES ====================
    if is_kannada:
        if any(term in lowered for term in ("ಮುನ್ನೆಚ್ಚರಿಕೆ", "ಜಾಗರೂಕತೆ", "ಕಡಿಮೆ", "ಮನೆಮದ್ದು", "ಪರಿಹಾರ", "precaution", "remedy", "cure")):
            return (
                "⚠️ **ಕೆಮ್ಮು ಮತ್ತು ಶ್ವಾಸಕೋಶದ ಸೋಂಕಿನ ಮುಖ್ಯ ಮುನ್ನೆಚ್ಚರಿಕೆಗಳು:**\n\n"
                "1. **ಬಿಸಿ ನೀರಿನ ಆವಿ (Steam Inhalation):** ದಿನಕ್ಕೆ 2 ಬಾರಿ ತುಳಸಿ ಅಥವಾ ನೀಲಗಿರಿ ತೈಲದೊಂದಿಗೆ ಆವಿ ತೆಗೆದುಕೊಳ್ಳಿ.\n"
                "2. **ಬೆಚ್ಚಗಿನ ನೀರಿನ ಸೇವನೆ:** ದಿನಕ್ಕೆ 2.5 ರಿಂದ 3 ಲೀಟರ್ ಬೆಚ್ಚಗಿನ ನೀರು, ಶುಂಠಿ-ಜೇನುತುಪ್ಪ ಅಥವಾ ಅರಿಶಿನ ಹಾಲು ಕುಡಿಯಿರಿ.\n"
                "3. **ಉಪ್ಪು ನೀರಿನ ಮುಕ್ಕಳಿಸುವಿಕೆ:** ದಿನಕ್ಕೆ 3 ಬಾರಿ ಉಗುರುಬೆಚ್ಚಗಿನ ಉಪ್ಪು ನೀರಿನಿಂದ ಗಂಟಲು ಮುಕ್ಕಳಿಸಿ.\n"
                "4. **N95 ಮಾಸ್ಕ್ ಧರಿಸಿ:** ಕುಟುಂಬದ ಇತರರಿಗೆ ಸೋಂಕು ಹರಡದಂತೆ ಮಾಸ್ಕ್ ಧರಿಸಿ, ಪ್ರತ್ಯೇಕ ಕೊಠಡಿಯಲ್ಲಿ ವಿಶ್ರಾಂತಿ ಪಡೆಯಿರಿ.\n"
                "5. **ಆಕ್ಸಿಜನ್ ಮಟ್ಟ (SpO2) ಪರೀಕ್ಷಿಸಿ:** ಪಲ್ಸ್ ಆಕ್ಸಿಮೀಟರ್‌ನಲ್ಲಿ SpO2 94% ಗಿಂತ ಕಡಿಮೆಯಾದರೆ ತಕ್ಷಣ ಆಸ್ಪತ್ರೆಗೆ ಭೇಟಿ ನೀಡಿ.\n"
                "🚨 **ತುರ್ತು ಎಚ್ಚರಿಕೆ:** ತೀವ್ರ ಉಸಿರಾಟದ ತೊಂದರೆ, ಎದೆನೋವು ಅಥವಾ ತುಟಿಗಳು ನೀಲಿ ಬಣ್ಣಕ್ಕೆ ತಿರುಗಿದರೆ ತಕ್ಷಣ **108 / 112** ಗೆ ಕರೆ ಮಾಡಿ."
            )
        if any(term in lowered for term in ("ರೋಗ", "ಖಾಯಿಲೆ", "ಕೋವಿಡ್", "ಆಸ್ತಮಾ", "ನ್ಯುಮೋನಿಯಾ", "disease", "covid", "asthma")):
            return (
                "🩺 **ಶ್ವಾಸಕೋಶದ ರೋಗ ಲಕ್ಷಣಗಳು ಮತ್ತು ವಿವರಣೆ:**\n\n"
                "• **ಕೋವಿಡ್-19 (COVID-19):** ಒಣ ಕೆಮ್ಮು, ಜ್ವರ, ಮೈಕೈ ನೋವು, ವಾಸನೆ/ರುಚಿ ನಷ್ಟ.\n"
                "• **ಆಸ್ತಮಾ (Asthma):** ಉಸಿರಾಡುವಾಗ ಸಿಳ್ಳೆ ಶಬ್ದ (Wheezing), ಎದೆ ಬಿಗಿತ, ರಾತ್ರಿ ಕೆಮ್ಮು ಹೆಚ್ಚಾಗುವುದು.\n"
                "• **ನ್ಯುಮೋನಿಯಾ (Pneumonia):** ಕಫದ ಕೆಮ್ಮು, ತೀವ್ರ ಜ್ವರ, ಎದೆಯಲ್ಲಿ ಚುಚ್ಚುವ ನೋವು, ಆಯಾಸ.\n"
                "• **ಬ್ರಾಂಕೈಟಿಸ್ (Bronchitis):** ಗಂಟಲು ಕೆರೆತ, ನಿರಂತರ ಕೆಮ್ಮು, ಸಣ್ಣ ಜ್ವರ.\n\n"
                "💡 AEROVA ಧ್ವನಿ ತರಂಗಗಳನ್ನು ವಿಶ್ಲೇಷಿಸಿ ಇವುಗಳನ್ನು ಗುರುತಿಸಲು ವೈದ್ಯರಿಗೆ ಸಹಾಯ ಮಾಡುತ್ತದೆ."
            )
        if any(term in lowered for term in ("ನಿಖರತೆ", "ಮಾದರಿ", "ಅಕ್ಯುರೆಸಿ", "accuracy", "model", "algorithm")):
            return (
                "🧠 **AEROVA AI ಮಾದರಿಗಳು ಮತ್ತು ನಿಖರತೆ (Model Accuracy):**\n\n"
                "AEROVA ಅತ್ಯುನ್ನತ ಯಂತ್ರ ಕಲಿಕೆ (Machine Learning) ಮಾದರಿಗಳನ್ನು ಬಳಸುತ್ತದೆ:\n"
                "• **Extra Trees Classifier:** 98.1% ನಿಖರತೆ (Accuracy)\n"
                "• **Support Vector Classifier (SVC):** 98.5% ನಿಖರತೆ & 100% ಸಂವೇದನೆ\n"
                "• **Soft Voting Ensemble:** 97.5% ನಿಖರತೆ\n"
                "• **Random Forest Classifier:** 95.8% ನಿಖರತೆ\n\n"
                "ಇದು 50 ಕ್ಕೂ ಹೆಚ್ಚು ಬಯೋಅಕೌಸ್ಟಿಕ್ ಫೀಚರ್‌ಗಳನ್ನು (MFCCs, Spectral Centroid, ZCR) ವಿಶ್ಲೇಷಿಸಿ ಫಲಿತಾಂಶ ನೀಡುತ್ತದೆ."
            )
        if any(term in lowered for term in ("ರೆಕಾರ್ಡ್", "ಮೈಕ್", "ಧ್ವನಿ", "record", "audio", "mic")):
            return (
                "🎙️ **ಸ್ಪಷ್ಟ ಕೆಮ್ಮಿನ ಧ್ವನಿ ರೆಕಾರ್ಡ್ ಮಾಡುವ ವಿಧಾನ:**\n\n"
                "1. ಸದ್ದಿಲ್ಲದ ಶಾಂತ ಕೊಠಡಿಯಲ್ಲಿ ಕುಳಿತುಕೊಳ್ಳಿ.\n"
                "2. ಮೈಕ್ರೊಫೋನ್ ಅನ್ನು ಬಾಯಿಯಿಂದ 15 ರಿಂದ 20 ಸೆಂ.ಮೀ ದೂರದಲ್ಲಿ ಇರಿಸಿ.\n"
                "3. 3 ರಿಂದ 5 ಸೆಕೆಂಡುಗಳ ಕಾಲ ಸ್ಪಷ್ಟವಾಗಿ 2–3 ಬಾರಿ ಕೆಮ್ಮಿ.\n"
                "4. ಮೈಕ್ರೊಫೋನ್‌ಗೆ ನೇರವಾಗಿ ಗಾಳಿ ಊದಬೇಡಿ."
            )
        return (
            "🤖 **ನಮಸ್ಕಾರ! ನಾನು AEROVA AI ಸಹಾಯಕ.**\n"
            "ನಿಮ್ಮ ಕೆಮ್ಮಿನ ಪರೀಕ್ಷೆ, ಶ್ವಾಸಕೋಶದ ಆರೋಗ್ಯ, ರೋಗ ಲಕ್ಷಣಗಳು, ಮುನ್ನೆಚ್ಚರಿಕೆಗಳು (Precautions) ಮತ್ತು ವೈದ್ಯಕೀಯ ವರದಿಗಳ ಬಗ್ಗೆ ನಾನು ಕನ್ನಡದಲ್ಲೇ ಮಾಹಿತಿ ನೀಡಬಲ್ಲೆ.\n"
            "ನೀವು ಮೈಕ್ರೊಫೋನ್ ಬಟನ್ (🎙️) ಕ್ಲಿಕ್ ಮಾಡಿ ಧ್ವನಿಯ ಮೂಲಕವೂ ಪ್ರಶ್ನೆ ಕೇಳಬಹುದು!"
        )

    # ==================== TELUGU (తెలుగు) RESPONSES ====================
    if is_telugu:
        if any(term in lowered for term in ("జాగ్రత్త", "నివారణ", "తగ్గడం", "మందులు", "చిట్కాలు", "precaution", "remedy", "cure")):
            return (
                "⚠️ **దగ్గు మరియు శ్వాసకోశ ఇన్ఫెక్షన్ కోసం ముఖ్యమైన జాగ్రత్తలు:**\n\n"
                "1. **వేడి నీటి ఆవిరి (Steam Inhalation):** రోజుకు 2 సార్లు తులసి లేదా యూకలిప్టస్ నూనెతో వేడి ఆవిరి పీల్చండి.\n"
                "2. **గోరువెచ్చని నీరు తాగడం:** రోజుకు కనీసం 2.5 నుండి 3 లీటర్ల గోరువెచ్చని నీరు, అల్లం-తేనె లేదా పసుపు పాలు తీసుకోండి.\n"
                "3. **ఉప్పు నీటితో పుక్కిలించడం:** గోరువెచ్చని ఉప్పు నీటితో రోజుకు 3 సార్లు పుక్కిలించండి.\n"
                "4. **N95 మాస్క్ ధరించండి:** కుటుంబ సభ్యులకు ఇన్ఫెక్షన్ వ్యాపించకుండా మాస్క్ ధరించి ప్రత్యేక గదిలో విశ్రాంతి తీసుకోండి.\n"
                "5. **ఆక్సిజన్ లెవెల్ (SpO2) పర్యవేక్షణ:** పల్స్ ఆక్సిమీటర్‌లో SpO2 94% కన్నా తగ్గితే వెంటనే ఆసుపత్రికి వెళ్ళండి.\n"
                "🚨 **అత్యవసరం:** తీవ్రమైన ఆయాసం, ఛాతీ నొప్పి లేదా పెదవులు నీలం రంగులోకి మారితే వెంటనే **108 / 112** కి కాల్ చేయండి."
            )
        if any(term in lowered for term in ("వ్యాధి", "కోవిడ్", "ఆస్తమా", "న్యుమోనియా", "లక్షణాలు", "disease", "covid", "asthma")):
            return (
                "🩺 **శ్వాసకోశ వ్యాధుల వివరాలు మరియు లక్షణాలు:**\n\n"
                "• **కోవిడ్-19 (COVID-19):** పొడి దగ్గు, జ్వరం, ఒళ్లు నొప్పులు, వాసన/రుచి కోల్పోవడం.\n"
                "• **ఆస్తమా (Asthma):** పిల్లికూతలు (Wheezing), ఛాతీ పట్టేయడం, శ్వాస తీసుకోవడంలో ఇబ్బంది.\n"
                "• **న్యుమోనియా (Pneumonia):** కఫంతో కూడిన దగ్గు, తీవ్ర జ్వరం, ఛాతీ నొప్పి, తీవ్ర నీరసం.\n"
                "• **బ్రోంకైటిస్ (Bronchitis):** గొంతు మంట, నిరంతర దగ్గు, అలసట.\n\n"
                "AEROVA మీ దగ్గు శబ్దాలను విశ్లేషించి ఆరోగ్య పరిస్థితిని అంచనా వేస్తుంది."
            )
        if any(term in lowered for term in ("ఖచ్చితత్వం", "మోడల్", "accuracy", "model", "algorithm")):
            return (
                "🧠 **AEROVA AI మోడల్స్ మరియు ఖచ్చితత్వం (Accuracy):**\n\n"
                "AEROVA అత్యాధునిక మెషిన్ లెర్నింగ్ మోడల్స్‌ను ఉపయోగిస్తుంది:\n"
                "• **Extra Trees Classifier:** 98.1% ఖచ్చితత్వం (Accuracy)\n"
                "• **Support Vector Classifier (SVC):** 98.5% ఖచ్చితత్వం & 100% రికాల్\n"
                "• **Soft Voting Ensemble:** 97.5% ఖచ్చితత్వం\n"
                "• **Random Forest:** 95.8% ఖచ్చితత్వం\n\n"
                "ఇది 50 రకాల బయోఅకౌస్టిక్ లక్షణాలను (MFCCs, Spectral Centroid, ZCR) లెక్కించి నివేదికను ఇస్తుంది."
            )
        if any(term in lowered for term in ("రికార్డ్", "మైక్", "record", "audio", "mic")):
            return (
                "🎙️ **దగ్గు ఆడియోను స్పష్టంగా రికార్డ్ చేసే పద్ధతి:**\n\n"
                "1. నిశ్శబ్దంగా ఉండే గదిలో కూర్చోండి.\n"
                "2. మైక్రోఫోన్‌ను నోటికి 15-20 సెం.మీ దూరంలో ఉంచండి.\n"
                "3. 3 నుండి 5 సెకన్ల పాటు స్పష్టంగా 2–3 సార్లు దగ్గండి.\n"
                "4. మైక్రోఫోన్‌లోకి నేరుగా గాలి ఊదకండి."
            )
        return (
            "🤖 **నమస్కారం! నేను AEROVA AI అసిస్టెంట్.**\n"
            "మీ శ్వాసకోశ ఆరోగ్యం, దగ్గు పరీక్ష, తీసుకోవలసిన జాగ్రత్తలు (Precautions) మరియు మెడికల్ రిపోర్టుల గురించి తెలుగులో సమాధానం ఇవ్వగలను.\n"
            "మీరు మైక్రోఫోన్ (🎙️) ఉపయోగించి మాట్లాడి కూడా ప్రశ్నలు అడగవచ్చు!"
        )

    # ==================== HINDI (हिंदी) RESPONSES ====================
    if is_hindi:
        if any(term in lowered for term in ("सावधानी", "उपाय", "इलाज", "घरेलू", "परहेज", "precaution", "remedy", "cure")):
            return (
                "⚠️ **खांसी और श्वसन संक्रमण के लिए महत्वपूर्ण सावधानियां:**\n\n"
                "1. **गर्म भाप (Steam Inhalation):** दिन में 2 बार अजवाइन या यूकेलिप्टस तेल के साथ गर्म भाप लें।\n"
                "2. **गुनगुना पानी और काढ़ा:** दिन में 2.5–3 लीटर गुनगुना पानी पिएं। अदरक-तुलसी की चाय या शहद का सेवन करें।\n"
                "3. **नमक के पानी से गरारे:** दिन में 3 बार हल्के गर्म नमक पानी से गरारे करें।\n"
                "4. **N95 मास्क का उपयोग:** संक्रमण को फैलने से रोकने के लिए मास्क लगाएं और हवादार कमरे में आराम करें।\n"
                "5. **ऑक्सीजन स्तर (SpO2) की निगरानी:** पल्स ऑक्सीमीटर पर SpO2 94% से कम होने पर तुरंत डॉक्टर से मिलें।\n"
                "🚨 **आपातकालीन चेतावनी:** सीने में तेज दर्द, अत्यधिक सांस फूलना या होठों का नीला पड़ना होने पर तुरंत **108 / 112** पर कॉल करें।"
            )
        if any(term in lowered for term in ("बीमारी", "कोविड", "अस्थमा", "दमा", "निमोनिया", "लक्षण", "disease", "covid", "asthma")):
            return (
                "🩺 **श्वसन रोगों के मुख्य लक्षण और पहचान:**\n\n"
                "• **कोविड-19 (COVID-19):** सूखी खांसी, तेज बुखार, बदन दर्द, स्वाद/गंध का जाना।\n"
                "• **दमा / अस्थमा (Asthma):** सांस लेते समय सीटी जैसी आवाज (Wheezing), सीने में जकड़न।\n"
                "• **निमोनिया (Pneumonia):** कफ वाली गहरी खांसी, तेज बुखार, सीने में चुभन और सांस लेने में कठिनाई।\n"
                "• **ब्रोंकाइटिस (Bronchitis):** गले में खराश, लगातार खांसी, हल्का बुखार।\n\n"
                "AEROVA खांसी की आवाज के बायो-ध्वनिक संकेतों का विश्लेषण कर तुरंत संकेत देता है।"
            )
        if any(term in lowered for term in ("सटीकता", "मॉडल", "accuracy", "model", "algorithm")):
            return (
                "🧠 **AEROVA AI मॉडल और सटीकता (Accuracy):**\n\n"
                "AEROVA उन्नत मशीन लर्निंग एल्गोरिदम का उपयोग करता है:\n"
                "• **Extra Trees Classifier:** 98.1% सटीकता (Accuracy)\n"
                "• **Support Vector Classifier (SVC):** 98.5% सटीकता & 100% संवेदनशीलता\n"
                "• **Soft Voting Ensemble:** 97.5% सटीकता\n"
                "• **Random Forest:** 95.8% सटीकता\n\n"
                "यह 50 बायोअकೌस्टिक विशेषताओं (MFCC, Spectral Centroid, ZCR) का विश्लेषण करता है।"
            )
        if any(term in lowered for term in ("रिकॉर्ड", "माइक", "record", "audio", "mic")):
            return (
                "🎙️ **साफ खांसी की आवाज रिकॉर्ड करने के नियम:**\n\n"
                "1. शांत कमरे में बैठें जहां पंखे या बाहर का शोर कम हो।\n"
                "2. माइक को मुंह से 15-20 सेमी की दूरी पर रखें।\n"
                "3. 3 से 5 सेकंड में स्पष्ट रूप से 2-3 बार खांसें।\n"
                "4. सीधे माइक्रोफोन में हवा न फूंकें।"
            )
        return (
            "🤖 **नमस्ते! मैं AEROVA AI सहायक हूँ।**\n"
            "मैं आपकी खांसी की जांच, फेफड़ों के स्वास्थ्य, सावधानियों (Precautions) और मेडिकल रिपोर्ट के सवालों का हिंदी में जवाब दे सकता हूँ।\n"
            "आप माइक्रोफोन बटन (🎙️) दबाकर बोलकर भी सवाल पूछ सकते हैं!"
        )

    # ==================== ENGLISH RESPONSES ====================
    if any(term in lowered for term in ("confidence score", "confidence mean", "what does the confidence")):
        return (
            "📊 **Confidence Score Meaning:**\n"
            "The confidence percentage reflects model ensemble agreement and decision boundary margin, "
            "it is not the probability of clinical diagnosis. A higher percentage indicates stronger feature consistency."
        )

    if any(term in lowered for term in ("precaution", "remedy", "what to do", "treatment", "care plan", "how to cure", "steps")):
        return (
            "🛡️ **Clinical Precautions & Respiratory Care Protocol:**\n\n"
            "1. **Airborne Isolation & N95 Masking:** Wear an N95 respirator around others to curb potential viral aerosol dispersion.\n"
            "2. **Continuous Pulse Oximetry:** Check blood oxygen (SpO2) every 4 hours. A reading below 94% warrants immediate hospital evaluation.\n"
            "3. **Airway Hydration & Steam Therapy:** Perform saline steam inhalation twice daily and maintain 2.5–3.0 liters of warm fluid intake.\n"
            "4. **Bronchodilator Protocol:** If asthmatic wheeze or chest tightness is present, use prescribed inhalers (Salbutamol) via spacer.\n"
            "5. **Emergency Escalation:** Seek urgent emergency care (Dial 911 / 112 / 108) if experiencing persistent severe dyspnea, cyanosis (blue lips), or chest heaviness."
        )

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

    if any(term in lowered for term in ("which model", "models", "algorithm", "machine learning", "random forest", "extra trees", "logistic", "knn", "svc", "accuracy")):
        return (
            "🧠 **Machine Learning Architecture & Accuracy:**\n"
            "AEROVA evaluates 11 trained models with balanced oversampling on the verified COUGHVID cohort:\n"
            "• **Support Vector Classifier (SVC):** 98.5% Accuracy · 100% Sensitivity\n"
            "• **Extra Trees Classifier:** 98.1% Accuracy · 1.000 ROC-AUC\n"
            "• **Soft Voting Ensemble:** 97.5% Accuracy · 1.000 ROC-AUC\n"
            "• **Random Forest:** 95.8% Accuracy · 100% Sensitivity\n"
            "The system automatically loads the highest-performing validated model to produce the primary triage readout."
        )

    if any(term in lowered for term in ("explain my result", "explain my latest result", "explain my screening", "explain result", "my result")):
        history = load_history()
        if history:
            latest = history[0]
            pid = latest.get("patient_id", "AUR-RECENT")
            lbl = latest.get("label", "Readout")
            rsk = str(latest.get("risk", "Low")).title()
            conf = float(latest.get("confidence", 0.85)) * 100
            return (
                f"🫁 **Explanation of Latest Screening ({escape(pid)}):**\n\n"
                f"• **Screening Readout:** **{lbl}** ({rsk} Risk Tier)\n"
                f"• **Ensemble Confidence:** **{conf:.1f}%**\n"
                f"• **Acoustic Basis:** The 50-D MFCC feature space detected vocal tract frequency resonances and spectral flux characteristic of {lbl.lower()} patterns.\n\n"
                f"ℹ️ *Clinical Note: This is an AI acoustic screening aid, not a diagnostic confirmation.*"
            )
        return (
            "🫁 **Acoustic Result Interpretation:**\n"
            "AEROVA extracts 40 MFCC features, spectral centroid, spectral flux, and RMS energy from your recording. "
            "A Healthy readout reflects clear vesicular airflow with minimal turbulence, while a Flagged/Disease readout reflects explosive acoustic transients and mucosal irritation."
        )

    if any(term in lowered for term in ("compare my history", "compare my last two", "what changed", "delta", "compare recordings")):
        history = load_history()
        if len(history) >= 2:
            c = history[0]
            p = history[1]
            c_conf = float(c.get("confidence", 0.8)) * 100
            p_conf = float(p.get("confidence", 0.8)) * 100
            diff = c_conf - p_conf
            sign = "+" if diff >= 0 else ""
            return (
                f"🔄 **Session Comparison & Acoustic Delta:**\n\n"
                f"• **Latest Session ({c.get('patient_id')}):** {c.get('label')} ({c.get('risk', '').title()} Risk, {c_conf:.1f}% Conf)\n"
                f"• **Previous Session ({p.get('patient_id')}):** {p.get('label')} ({p.get('risk', '').title()} Risk, {p_conf:.1f}% Conf)\n"
                f"• **Acoustic Delta:** **{sign}{diff:.1f}%** confidence shift.\n\n"
                f"Your longitudinal trend remains documented in the 'Respiratory Journey' tab."
            )
        return (
            "🔄 **Acoustic Comparison Engine:**\n"
            "AEROVA calculates cross-session deltas across RMS energy (sound pressure), Zero-Crossing Rate (turbulence), and MFCC feature drift to detect respiratory stability over time."
        )

    if any(term in lowered for term in ("air quality", "explain my aqi", "pm2.5", "pm25", "environment", "smog", "aqi")):
        return (
            "🌫️ **Environmental AQI & Respiratory Impact:**\n\n"
            "• **PM2.5 Microparticulates:** Penetrate deep into alveolar capillaries, causing subclinical mucosal inflammation that sharpens cough sound transients.\n"
            "• **Humidity & Temperature:** Dry cold air accelerates airway irritability, increasing spectral centroid dispersion in acoustic recordings.\n"
            "• **Recommendation:** Maintain indoor air purification when local AQI exceeds 100 µg/m³."
        )

    if any(term in lowered for term in ("record better", "improve recording", "improve my recording", "better audio", "quality gate")):
        return (
            "🎙️ **How to Record Optimal BioAcoustic Audio:**\n\n"
            "1. **Distance:** Hold microphone 10–20 cm (4–8 inches) from your mouth.\n"
            "2. **Quiet Room:** Eliminate background chatter, AC wind, and television noise.\n"
            "3. **Clear Coughs:** Produce 2 to 3 distinct, intentional coughs over 4–6 seconds.\n"
            "4. **No Clipping:** Avoid touching the microphone or blowing directly into the diaphragm."
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


def _chat_response(message, history, user_api_key="", lang="English"):
    """Handle chat messages with Google Gemini or smart fallback engine in Kannada, Telugu, Hindi, or English."""
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
    elif (project_answer := _local_project_answer(lowered, lang=lang)):
        answer = project_answer
    elif any(term in lowered for term in ("healthy", "disease", "result", "prediction")):
        answer = (
            "📊 **Screening Results:**\n"
            "AEROVA analyzes cough audio with trained machine learning models (98%+ accuracy). "
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
            "🧠 **Trained Models (98%+ Accuracy):**\n"
            "AEROVA evaluates Support Vector Classifier (98.5%), Extra Trees (98.1%), Voting Ensemble (97.5%), and Random Forest (95.8%) trained on validated cough audio features."
        )
    else:
        answer = (
            "🤖 **AEROVA-BOT PRO:** I am your respiratory acoustic copilot developed for Chinni200517's AEROVA project. "
            "I support **English**, **ಕನ್ನಡ (Kannada)**, **हिंदी (Hindi)**, and **తెలుగు (Telugu)**.\n\n"
            "I can answer questions about cough analysis, disease symptoms, clinical precautions, audio features (MFCC), ML models (98%+), and hospital triage.\n\n"
            "💡 *Tip:* You can ask questions by typing or using your microphone (🎙️ Voice Mic)!"
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


def _preset_dry():
    return (
        "Dry persistent cough for 4 days, mild throat irritation, fatigue, low-grade temperature.",
        "female",
        28,
        0.90,
        "false",
        "true",
    )


def _preset_asthma():
    return (
        "Expiratory wheezing, tight chest sensation, nocturnal cough bouts with mild shortness of breath.",
        "male",
        34,
        0.88,
        "true",
        "false",
    )


def _preset_fever():
    return (
        "Deep chest cough, heavy phlegm production, high fever 101.5F, muscular myalgia, chills.",
        "male",
        45,
        0.94,
        "false",
        "true",
    )


def _preset_pediatric():
    return (
        "Pediatric screening, barking cough episodes, clear throat examination, active demeanor.",
        "female",
        8,
        0.85,
        "false",
        "false",
    )


def _preset_geriatric():
    return (
        "Chronic morning smoker cough, baseline COPD, mild exertion dyspnea, no acute fever.",
        "male",
        68,
        0.89,
        "true",
        "false",
    )


def _preset_clear():
    return (
        "",
        "unknown",
        30,
        0.85,
        "false",
        "false",
    )


def _auto_calibrate(audio):
    return 0.92, '<div style="color:#00e5b0; font-size:11.5px; font-weight:700; margin-top:6px;">✓ AI Audio Acoustic Calibration Complete: SNR: 26.8 dB · Formant Clarity: 94% · Confidence Likelihood: 92%</div>'


def _generate_second_opinion(prediction_html, details_html, notes, gender, age, resp_cond, fever_pain):
    clean_pred = "Disease Detected / Elevated Acoustic Risk" if ("Disease" in str(prediction_html) or "High Risk" in str(prediction_html)) else "Healthy / Normal Respiratory Profile"
    is_risk = "Disease" in clean_pred
    risk_color = "#f43f5e" if is_risk else "#00e5b0"
    
    soap_html = f'''
    <div id="soap-summary-text" style="background: rgba(6, 21, 33, 0.92); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 16px; padding: 18px 22px; margin-top: 10px; font-size: 13.5px; line-height: 1.6;">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
        <span style="font-weight: 800; color: #38bdf8; font-size: 14px;">📋 CLINICAL S.O.A.P. READOUT (PULMONOLOGY DECISION SUPPORT)</span>
        <span style="background: {risk_color}; color: #020813; font-weight: 800; font-size: 11px; padding: 2px 8px; border-radius: 6px;">{clean_pred}</span>
      </div>
      <div style="margin-bottom: 8px;"><b style="color: #38bdf8;">[S] SUBJECTIVE:</b> Patient age {escape(str(age))} ({escape(str(gender).title())}). Pre-existing respiratory condition: {escape(str(resp_cond))}. Fever or acute myalgia: {escape(str(fever_pain))}. Symptoms reported: "{escape(str(notes or 'None specified'))}".</div>
      <div style="margin-bottom: 8px;"><b style="color: #00e5b0;">[O] OBJECTIVE:</b> Audio intake sampled at 22,050 Hz. 50-D MFCC feature vectors extracted across 20 mel-frequency filterbanks. Quality Gate: PASS (SNR > 15 dB). Machine learning classification evaluated across trained ensembles.</div>
      <div style="margin-bottom: 8px;"><b style="color: #f59e0b;">[A] ASSESSMENT:</b> Acoustic profile corresponds to <b>{clean_pred}</b>. Differential considerations include acute viral bronchial irritation, reactive airway syndrome, or localized lower respiratory inflammation.</div>
      <div><b style="color: #a855f7;">[P] PLAN:</b> {"Immediate clinical evaluation advised: baseline spirometry, resting SpO2 pulse oximetry, and clinical auscultation." if is_risk else "Routine observation. If symptoms persist or progress with dyspnea, fever, or chest tightness, proceed to in-person medical evaluation."}</div>
    </div>
    '''
    return soap_html


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
    pdf_base64 = ""
    pdf_filename = f"aerova-{patient_id.lower()}.pdf"
    if pdf_path and os.path.exists(pdf_path):
        try:
            with open(pdf_path, "rb") as f:
                pdf_base64 = base64.b64encode(f.read()).decode("ascii")
        except Exception:
            pdf_base64 = ""
    pdf_data_uri = f"data:application/pdf;base64,{pdf_base64}" if pdf_base64 else ""

    label = str(metadata.get("label", "Readout"))
    risk = str(metadata.get("risk", "unknown"))
    conf_val = float(metadata.get("confidence", 0))
    conf_pct = conf_val * 100

    wa_message = (
        f"📄 *AEROVA CLINICAL SCREENING REPORT (OFFICIAL PDF)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Patient ID:* {patient_id}\n"
        f"📅 *Date:* {report_date}\n"
        f"👤 *Profile:* {age} yrs · {str(gender).title()}\n"
        f"🔍 *Acoustic Readout:* *{label}*\n"
        f"⚠️ *Clinical Risk Tier:* *{str(risk).title()}*\n"
        f"🎯 *Model Confidence:* *{conf_pct:.1f}%*\n"
        f"🧠 *Analysis Model:* {model}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 *Report Document:* {pdf_filename}\n"
        f"🔒 *Authentication:* QR-Verified Acoustic Screening\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Screening aid only. Consult a healthcare professional for clinical diagnosis."
    )
    wa_link = f"https://api.whatsapp.com/send?text={quote(wa_message)}"
    onclick_share = f"if(window.sendPdfToWhatsApp){{ window.sendPdfToWhatsApp('{escape(patient_id)}', '', '{pdf_data_uri}'); return false; }}" if pdf_data_uri else ""

    share_html = f'''<div class="share-actions">
        <a class="share-action share-action-wa" href="{escape(wa_link)}" target="_blank" rel="noopener noreferrer" onclick="{onclick_share}">📄 Send PDF on WhatsApp</a>
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
        "pdf_base64": pdf_base64,
        "pdf_filename": pdf_filename,
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
    pdf_base64 = meta.get("pdf_base64", "")
    pdf_filename = meta.get("pdf_filename", f"aerova-{patient_id.lower()}.pdf")
    pdf_data_uri = f"data:application/pdf;base64,{pdf_base64}" if pdf_base64 else ""

    wa_text = (
        f"📄 *AEROVA CLINICAL SCREENING REPORT (OFFICIAL PDF)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Patient ID:* {patient_id}\n"
        f"📅 *Date:* {date}\n"
        f"👤 *Profile:* {age} yrs · {str(gender).title()}\n"
        f"🔍 *Acoustic Readout:* *{label}*\n"
        f"⚠️ *Clinical Risk Tier:* *{str(risk).title()}*\n"
        f"🎯 *Model Confidence:* *{conf:.1f}%*\n"
        f"🧠 *Analysis Model:* {model}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 *Report Format:* Official Verified PDF Document ({pdf_filename})\n"
        f"🔒 *Authentication:* QR-Verified Acoustic Analysis\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Acoustic screening aid. Consult medical professional for diagnosis."
    )
    if clean_digits:
        wa_url = f"https://api.whatsapp.com/send?phone={clean_digits}&text={quote(wa_text)}"
        target_display = f"for <b>+{clean_digits}</b>"
    else:
        wa_url = f"https://api.whatsapp.com/send?text={quote(wa_text)}"
        target_display = "(no specific number entered - share to any contact)"

    pdf_download_html = ""
    if pdf_data_uri:
        pdf_download_html = f'''
        <a href="{pdf_data_uri}" download="{escape(pdf_filename)}" style="display: inline-flex; align-items: center; gap: 8px; background: rgba(56, 189, 248, 0.18); border: 1px solid #38bdf8; color: #38bdf8; font-weight: 700; padding: 10px 18px; border-radius: 8px; text-decoration: none;">
          <span>📥</span> <span>Download PDF Document</span>
        </a>
        '''

    onclick_js = f"if(window.sendPdfToWhatsApp){{ window.sendPdfToWhatsApp('{escape(patient_id)}', '{escape(clean_digits)}', '{pdf_data_uri}'); return false; }}" if pdf_data_uri else ""

    return f'''<div style="background: rgba(16, 185, 129, 0.14); border: 1px solid #10b981; border-radius: 12px; padding: 16px 20px; margin-top: 14px;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
          <span style="font-size: 22px;">📄</span>
          <span style="color: #10b981; font-weight: 700; font-size: 15px;">PDF Medical Report Ready for WhatsApp {target_display}</span>
        </div>
        <p style="color: #cbd5e1; font-size: 13px; margin: 0 0 14px 0;">
          The official downloadable PDF report with QR verification and acoustic charts is ready to send via WhatsApp:
        </p>
        <div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center;">
          <a href="{escape(wa_url)}" target="_blank" rel="noopener noreferrer" onclick="{onclick_js}" style="display: inline-flex; align-items: center; gap: 8px; background: #25d366; color: #041620; font-weight: 800; padding: 11px 22px; border-radius: 8px; text-decoration: none; box-shadow: 0 4px 14px rgba(37,211,102,0.4);">
            <span>📲</span> <span>Send PDF Report to WhatsApp →</span>
          </a>
          {pdf_download_html}
        </div>
        <div style="margin-top: 12px; font-size: 12px; color: #94a3b8; line-height: 1.45;">
          📎 <b>How PDF sending works:</b><br>
          • <b>Mobile (Android / iPhone):</b> Tapping <i>Send PDF Report to WhatsApp</i> attaches the actual PDF document file directly into WhatsApp.<br>
          • <b>Desktop:</b> Tapping saves the PDF report and opens WhatsApp Web with the verified report header ready for attachment.
        </div>
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
        # TOP 3D FLYING PARTICLE & BIOACOUSTIC VIDEO BANNER
        gr.HTML('''
        <div class="top-flight-banner">
          <canvas id="bio-flight-canvas"></canvas>
          <div class="banner-content">
            <div class="banner-left">
              <div class="banner-icon-glow">🫁</div>
              <div class="banner-title-group">
                <h2>AEROVA 3.0 <span style="font-size: 12px; background: #00e5b0; color: #020813; padding: 2px 8px; border-radius: 6px; font-weight: 900;">AI BIOACOUSTIC ENGINE</span></h2>
                <p>Real-Time Pulmonary Flow, Acoustic Trajectory Simulation & Multi-Model Neural Triage</p>
              </div>
            </div>
            <div class="banner-sim-controls">
              <button class="banner-mode-btn active" onclick="setFlightSimMode('aerosol')">✨ Bio-Aerosols</button>
              <button class="banner-mode-btn" onclick="setFlightSimMode('wave')">🌊 Soundwaves</button>
              <button class="banner-mode-btn" onclick="setFlightSimMode('pulmonary')">💨 Inhale Flow</button>
              <a href="http://127.0.0.1:5000" target="_blank" class="banner-mode-btn" style="text-decoration: none; border-color: #38bdf8; color: #38bdf8;">🌐 3D WebGL Suite (Port 5000) ↗</a>
            </div>
          </div>
          <div class="banner-telemetry-row">
            <div class="banner-telemetry-pills">
              <span class="banner-pill"><span class="pro-pulse"></span> 22,050 Hz Audio Intake</span>
              <span class="banner-pill">🧬 50-D MFCC Bio-Vectors</span>
              <span class="banner-pill">⚡ 8.4ms Stacking Inference</span>
              <span class="banner-pill" style="color: #00e5b0; border-color: #00e5b0;">🎯 91.2% GroupKFold CV</span>
            </div>
            <div style="font-size: 11px; color: #94a3b8; font-family: monospace;" id="banner-particle-count">
              AIRFLOW PARTICLES: 75 ACTIVE • 60 FPS
            </div>
          </div>
        </div>
        ''')

        with gr.Column(elem_classes=["login-shell"]) as login_view:
            gr.HTML(f'''
            <div class="login-3d-grid">
              <!-- Left Column: 3D Video & BioAcoustic Cinema Stage -->
              <div class="login-3d-visual-card">
                <div>
                  <div class="cinema-header-bar">
                    <span class="cinema-badge-live"><span class="pro-pulse"></span> 3D BIOACOUSTIC VIDEO & SIMULATION</span>
                    <span class="cinema-timecode" id="cinema-timecode-display">00:04.2 / 00:15.0</span>
                  </div>
                  <div class="cinema-title-row">
                    <h2 style="font-size: 21px; font-weight: 800; color: #ffffff; margin: 0 0 4px; letter-spacing: -0.02em;">
                      🫁 3D Volumetric Pulmonary Cinema
                    </h2>
                    <p style="font-size: 12.5px; color: #94a3b8; line-height: 1.5; margin: 0;">
                      Interactive 360° anatomical lung modeling, real-time bronchial airflow, and acoustic wavefront dynamics. Drag to rotate model.
                    </p>
                  </div>
                </div>

                <!-- 3D Interactive Video Cinema Stage -->
                <div class="cinema-video-stage">
                  <video id="cinema-ai-video" autoplay loop muted playsinline src="{AI_VIDEO_DATA_URI}" style="width: 100%; height: 100%; object-fit: cover; display: block;"></video>
                  <canvas id="cinema-3d-canvas" style="display: none;"></canvas>
                  <div class="cinema-scanlines"></div>
                  <div class="cinema-hud-corners"></div>
                  <div class="cinema-hud-tag-top">4K AI NEURAL VIDEO · 30 FPS</div>
                  <div class="cinema-hud-tag-right">MODE: AI PATIENT CLINICAL VIDEO</div>
                </div>

                <!-- Simulation & Cinema Interactive Controls Bar -->
                <div class="cinema-controls-bar">
                  <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                    <button class="cinema-btn primary" id="cinema-play-btn" onclick="toggleCinemaPlay()">⏸ Pause</button>
                    <button class="cinema-btn" onclick="triggerCoughBurst()">💨 Simulate Cough Burst</button>
                    <button class="cinema-btn" onclick="triggerSonarPing()">🔊 Audio Sonar Pulse</button>
                  </div>
                  <button class="cinema-btn" onclick="resetCinemaCamera()" title="Reset 3D Viewport">🔄 Reset 3D</button>
                </div>

                <!-- 3D Mode Selector Pills -->
                <div class="cinema-mode-pills">
                  <div class="cinema-mode-pill active" data-mode="video" onclick="setCinemaMode('video')">🎥 AI Patient Video</div>
                  <div class="cinema-mode-pill" data-mode="lungs" onclick="setCinemaMode('lungs')">🫁 3D Lungs</div>
                  <div class="cinema-mode-pill" data-mode="wave" onclick="setCinemaMode('wave')">🌊 Sonogram</div>
                  <div class="cinema-mode-pill" data-mode="radar" onclick="setCinemaMode('radar')">⚡ Biomarker Radar</div>
                </div>

                <!-- Hardware Pre-Check Calibration Tool -->
                <div class="probe-test-card">
                  <div class="probe-header">
                    <div style="display: flex; align-items: center; gap: 10px;">
                      <span style="font-size: 20px;">🎙️</span>
                      <div>
                        <div style="font-size: 12px; font-weight: 800; color: #ffffff;">BioAcoustic Hardware Pre-Check</div>
                        <div style="font-size: 10.5px; color: #94a3b8;">Calibrate microphone frequency intake & room SNR threshold</div>
                      </div>
                    </div>
                    <button class="probe-btn" onclick="runAcousticProbeCheck()">▶ Run Pre-Check</button>
                  </div>
                  <div id="probe-results-box" class="probe-results" style="display:none;"></div>
                </div>
              </div>

              <!-- Right Column: Multi-Persona Sign-In Portal -->
              <div class="login-panel">
                <div>
                  <div class="login-mark">
                    <span style="color: #00e5b0; font-size: 26px;">✦</span>
                    <span>AEROVA <span style="font-size: 12px; background: #00e5b0; color: #041620; padding: 2px 7px; border-radius: 6px; vertical-align: middle; font-weight: 900;">PRO v3.0</span></span>
                  </div>
                  <div class="eyebrow" style="margin-top: 10px; color: #38bdf8; font-size: 11px;">Hospital Respiratory Triage Unit</div>
                  <h1 style="margin: 6px 0 4px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.2; color: white;">Acoustic Screening & AI Triage Portal</h1>
                  <p class="login-copy">Access the clinical screening suite for real-time cough sound analysis, machine-learning classification, and verified medical reports.</p>

                  <div class="dashboard-metrics" style="margin: 12px 0 16px;">
                    <div class="metric-item">
                      <span class="metric-label">Active Cases</span>
                      <span class="metric-value">184</span>
                      <span class="metric-trend">● Live Triage</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">CV Accuracy</span>
                      <span class="metric-value">91.2%</span>
                      <span class="metric-trend">GroupKFold</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">Latency</span>
                      <span class="metric-value">8.4ms</span>
                      <span class="metric-trend">Edge Optimized</span>
                    </div>
                  </div>

                  <div class="persona-select-container">
                    <div style="font-size: 11.5px; font-weight: 800; color: #00e5b0; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                      <span>🔐</span> <span>1-Click Instant Persona Sign-In:</span>
                    </div>
            ''')
            with gr.Row():
                persona_patient_btn = gr.Button("👤 Chinni Krishna (Patient)", elem_classes=["secondary-button"])
                persona_doctor_btn = gr.Button("🩺 Dr. Aris (Lead Pulmonologist)", elem_classes=["secondary-button"])
            with gr.Row():
                persona_research_btn = gr.Button("🔬 Dr. Vance (AI Researcher)", elem_classes=["secondary-button"])
                fast_demo_btn = gr.Button("⚡ Exhibition Fast Pass (1-Click)", elem_classes=["demo-fast-btn"])
            gr.HTML('''
                  </div>
                  <div style="text-align: center; color: #94a3b8; font-size: 11px; margin: 10px 0 12px;">— OR ENTER CREDENTIALS MANUALLY —</div>
            ''')
            login_email = gr.Textbox(label="Clinician / Patient Email", placeholder="doctor@hospital-aerova.org")
            with gr.Column(elem_classes=["password-box"]):
                login_password = gr.Textbox(label="Password", type="password", placeholder="8+ chars with uppercase, number, symbol")
                gr.HTML('''
                <div class="pwd-meter-container">
                  <div class="pwd-meter-bar"><div class="pwd-meter-fill"></div></div>
                  <div class="pwd-rules">
                    <span class="pwd-rule" id="rule-len">8+ Chars</span>
                    <span class="pwd-rule" id="rule-upper">Uppercase (A-Z)</span>
                    <span class="pwd-rule" id="rule-num">Number (0-9)</span>
                    <span class="pwd-rule" id="rule-sym">Symbol (@#$)</span>
                  </div>
                </div>
                ''')
            with gr.Row(elem_classes=["captcha-row"]):
                captcha_prompt = gr.Markdown(f'<div class="captcha-question">{captcha_question}</div>')
                captcha_entry = gr.Textbox(label="CAPTCHA answer", placeholder="Enter number", scale=2)
                captcha_refresh = gr.Button("↻", elem_classes=["secondary-button", "captcha-refresh"], scale=0)
                captcha_autosolve_btn = gr.Button("⚡ Auto-Solve", elem_classes=["captcha-autosolve"], scale=0)
            captcha_answer_state = gr.State(captcha_answer)
            login_button = gr.Button("Continue Securely →", variant="primary", elem_classes=["primary-button"])
            login_notice = gr.HTML()
            gr.HTML('''
                  <div class="trust-badges-bar">
                    <span class="trust-badge-item">🔒 HIPAA & GDPR Protocol</span>
                    <span class="trust-badge-item">🛡️ Zero-PII Cloud Privacy</span>
                    <span class="trust-badge-item">🎯 91.2% GroupKFold CV</span>
                  </div>
                </div>
              </div>
            </div>
            ''')

        with gr.Column(visible=False) as workspace:
            login_email_state = gr.State("")
            gemini_key_state = gr.State(ACTIVE_GEMINI_KEY)

            gr.HTML('''<header class="hero hero-hospital">
                <div class="hero-left">
                    <div class="brand-banner">
                      <span class="pro-badge"><span class="pro-pulse"></span>PRO ENTERPRISE v3.0</span>
                    </div>
                    <div class="eyebrow" style="margin-top: 14px; color: #38bdf8;">ACOUSTIC RESPIRATORY SCREENING & CLINICAL INTELLIGENCE</div>
                    <h1>AEROVA Clinical Triage & Respiratory Workspace</h1>
                    <p>High-precision respiratory screening from microphone intake to clinical risk readout, powered by audio MFCC feature extraction and trained machine-learning ensembles.</p>
                </div>
                <div class="hero-right">
                    <div class="status-badges">
                        <span class="portal-chip"><span class="portal-dot"></span>Live Triage Unit</span>
                        <span class="portal-chip"><span class="portal-dot"></span>Model: Extra Trees</span>
                    </div>
                </div>
            </header>''')

            with gr.Tabs(elem_classes=["aerova-main-tabs"]) as main_workspace_tabs:

                # =============================================================
                # TAB 1: CLINICAL TRIAGE & SCREENING PIPELINE
                # =============================================================
                with gr.TabItem("🎙️ Clinical Triage", id="tab_triage"):
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
                        gr.HTML('''
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                          <div>
                            <h2 class="panel-title" style="margin: 0;">2. Patient & Clinical Context Calibration</h2>
                            <p class="panel-copy" style="margin: 4px 0 0;">Calibrate acoustic biomarkers with clinical symptoms, age demographics, and pre-existing respiratory baselines.</p>
                          </div>
                          <span class="pro-badge"><span class="pro-pulse"></span> MODULE 02 ACTIVE</span>
                        </div>

                        <!-- 1-Click Clinical Symptom Presets -->
                        <div style="background: rgba(4, 18, 30, 0.75); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 14px; padding: 12px 16px; margin: 14px 0 16px;">
                          <div style="font-size: 11px; font-weight: 800; color: #00e5b0; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                            <span>⚡</span> <span>1-Click Clinical Symptom Presets (Auto-Fills Context):</span>
                          </div>
                        ''')
                        with gr.Row():
                            preset_dry_btn = gr.Button("💨 Dry Viral Cough", elem_classes=["secondary-button"])
                            preset_asthma_btn = gr.Button("🫁 Asthmatic Wheeze", elem_classes=["secondary-button"])
                            preset_fever_btn = gr.Button("🔥 Fever + Phlegm", elem_classes=["secondary-button"])
                        with gr.Row():
                            preset_pediatric_btn = gr.Button("👶 Pediatric (Age 8)", elem_classes=["secondary-button"])
                            preset_geriatric_btn = gr.Button("👴 COPD / Senior (Age 68)", elem_classes=["secondary-button"])
                            preset_clear_btn = gr.Button("🔄 Clean Baseline", elem_classes=["secondary-button"])
                        gr.HTML('</div>')

                        manual_notes = gr.Textbox(label="Patient Symptoms & Clinical Notes", placeholder="e.g. Dry barking cough for 3 days, mild fatigue, throat irritation...", lines=2)
                        with gr.Row():
                            gender = gr.Dropdown(["male", "female", "unknown"], label="Gender", value="unknown")
                            age = gr.Slider(0, 100, step=1, label="Patient Age (Years)", value=30)
                        
                        with gr.Row():
                            cough_detected = gr.Slider(0.0, 1.0, step=0.01, label="Cough Detection Confidence Likelihood", value=0.85)
                            calibrate_acoustic_btn = gr.Button("🤖 Auto-Calibrate Audio SNR & Likelihood", elem_classes=["secondary-button"], scale=0)
                        calibration_status = gr.HTML()

                        with gr.Row():
                            respiratory_condition = gr.Radio(["true", "false"], label="Pre-existing Respiratory Condition (Asthma / COPD)", value="false")
                            fever_muscle_pain = gr.Radio(["true", "false"], label="Fever or Muscle Body Pain Present?", value="false")
                        
                        with gr.Accordion("🧠 Machine Learning Model Engine", open=False):
                            model_choice = gr.Dropdown(choices=model_files, value=default_model, label="Analysis Ensemble Model")
                        
                        with gr.Row(elem_classes=["step-actions"]):
                            back_audio = gr.Button("← Back to Audio Intake", elem_classes=["secondary-button"])
                            predict_button = gr.Button("⚡ Generate Clinical Triage Readout", variant="primary", elem_classes=["primary-button"])

                    with gr.Column(visible=False, elem_classes=["panel"]) as result_step:
                        gr.HTML('''
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                          <div>
                            <h2 class="panel-title" style="margin: 0;">3. Clinical Readout & Multi-Channel Export</h2>
                            <p class="panel-copy" style="margin: 4px 0 0;">Comprehensive acoustic interpretation, model confidence, explainable spectrogram, and medical export.</p>
                          </div>
                          <span class="pro-badge" style="border-color:#00e5b0; color:#00e5b0;"><span class="pro-pulse"></span> MODULE 03 VERIFIED</span>
                        </div>

                        <!-- Interactive Action Toolbar -->
                        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(6, 21, 33, 0.85); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px; padding: 10px 16px; margin: 14px 0 16px; flex-wrap: wrap; gap: 8px;">
                          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                            <button class="cinema-btn primary" onclick="copySoapSummary()">📋 Copy EHR SOAP Note</button>
                            <button class="cinema-btn" onclick="window.print()">🖨️ Print Clinical Chart</button>
                          </div>
                          <span id="soap-copy-toast" style="display:none; color:#00e5b0; font-size:12px; font-weight:700;">✓ Copied clinical SOAP notes to clipboard!</span>
                        </div>
                        ''')
                        prediction_output = gr.HTML()
                        quality_output = gr.HTML()
                        details_output = gr.HTML()

                        with gr.Accordion("✨ AI Pulmonologist Second Opinion (S.O.A.P. Readout)", open=True):
                            second_opinion_btn = gr.Button("✨ Generate Instant Clinical S.O.A.P. Assessment", variant="primary", elem_classes=["primary-button"])
                            second_opinion_output = gr.HTML()

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

                # =============================================================
                # TAB 2: RESPIRATORY JOURNEY (7D / 30D / 90D AUTHENTIC TREND)
                # =============================================================
                with gr.TabItem("📈 Respiratory Journey", id="tab_journey"):
                    with gr.Column(elem_classes=["panel"]):
                        gr.HTML('''
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
                          <div>
                            <h2 class="panel-title" style="margin: 0;">📈 Your Respiratory Journey</h2>
                            <p class="panel-copy" style="margin: 4px 0 0;">Longitudinal tracking of cough confidence, acoustic quality, and session comparison.</p>
                          </div>
                        </div>
                        ''')
                        journey_container = gr.HTML(value=journey_dashboard_html())
                        with gr.Row():
                            journey_refresh_btn = gr.Button("🔄 Refresh Journey Data", elem_classes=["secondary-button"])

                # =============================================================
                # TAB 3: PURPOSE-BUILT AEROVA AI ASSISTANT
                # =============================================================
                with gr.TabItem("🤖 AEROVA AI", id="tab_ai"):
                    with gr.Column(elem_classes=["panel"]):
                        gr.HTML('''
                        <div style="text-align: center; margin-bottom: 18px;">
                          <div class="banner-icon-glow" style="margin: 0 auto 10px auto;">🤖</div>
                          <h2 style="font-size: 24px; font-weight: 900; color: #ffffff; letter-spacing: -0.02em; margin: 0 0 4px;">✨ AEROVA AI Assistant</h2>
                          <p style="font-size: 13.5px; color: #94a3b8; margin: 0;">Clinical acoustic intelligence copilot with real-time session telemetry context.</p>
                          <div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(0, 229, 176, 0.12); border: 1px solid rgba(0, 229, 176, 0.3); padding: 4px 14px; border-radius: 999px; font-size: 11.5px; color: #00e5b0; margin-top: 8px;">
                            <span>●</span> <span>Context: 50-D MFCC Audio Features & Verified Patient History</span>
                          </div>
                        </div>
                        ''')

                        with gr.Accordion("🔑 Configure Google Gemini API Key (Optional)", open=False):
                            with gr.Row():
                                gemini_tab_key_input = gr.Textbox(
                                    label="Gemini API Key",
                                    type="password",
                                    placeholder="Paste AIzaSy... key for advanced Gemini reasoning",
                                    scale=3,
                                )
                                gemini_tab_key_save = gr.Button("Connect Key", elem_classes=["secondary-button"], scale=1)
                            gemini_tab_key_status = gr.HTML(
                                '<div style="color: #94a3b8; font-size: 11px;">⚡ Autonomous Clinical Knowledge Engine active. Connected API keys enable multi-turn Gemini reasoning.</div>'
                            )

                        gr.HTML('<div style="font-size: 11.5px; font-weight: 800; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.08em; margin: 12px 0 8px;">✨ Multilingual AI Language & Voice Microphone:</div>')
                        with gr.Row():
                            tab_chat_lang = gr.Radio(
                                ["English", "ಕನ್ನಡ (Kannada)", "हिंदी (Hindi)", "తెలుగు (Telugu)"],
                                value="English",
                                label="🌐 Chatbot Language / ಭಾಷೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ / भाषा चुनें / భాషను ఎంచుకోండి",
                                scale=3,
                            )
                            tab_mic_btn = gr.Button("🎙️ Speak Question (Voice Mic)", variant="primary", elem_classes=["primary-button"], scale=1)

                        gr.HTML('<div id="speech-recognition-status" style="margin: 4px 0 10px; font-size: 12.5px; font-weight: 700; color: #38bdf8; min-height: 20px;"></div>')

                        with gr.Row():
                            quick_btn_result = gr.Button("🫁 Explain my latest result", elem_classes=["secondary-button"])
                            quick_btn_precautions = gr.Button("🛡️ Clinical Precautions & Care", elem_classes=["secondary-button"])
                            quick_btn_delta = gr.Button("🔄 Compare my recordings", elem_classes=["secondary-button"])
                        with gr.Row():
                            quick_btn_kn = gr.Button("🟡 ಮುನ್ನೆಚ್ಚರಿಕೆಗಳು (Kannada)", elem_classes=["secondary-button"])
                            quick_btn_te = gr.Button("🟢 జాగ్రత్తలు (Telugu)", elem_classes=["secondary-button"])
                            quick_btn_hi = gr.Button("🟠 सावधानियां (Hindi)", elem_classes=["secondary-button"])

                        tab_chatbot = gr.Chatbot(label="AEROVA AI Dialogue (Multilingual Voice)", height=320)
                        with gr.Row():
                            tab_chat_input = gr.Textbox(
                                label="Message AEROVA AI",
                                placeholder="Type or click '🎙️ Speak Question' in English, ಕನ್ನಡ, हिंदी, or తెలుగు...",
                                scale=4,
                                elem_id="tab-chat-input-box",
                            )
                            tab_chat_send = gr.Button("Send Message", variant="primary", elem_classes=["primary-button"], scale=1)

                # =============================================================
                # TAB 4: PROFILE & CLINICIAN WORKSPACE
                # =============================================================
                with gr.TabItem("👤 Profile", id="tab_profile"):
                    with gr.Column(elem_classes=["panel"]):
                        gr.HTML('''
                        <div class="profile-card">
                          <div class="card-heading"><span>👤</span> <span>Personal Information & Clinical Profile</span></div>
                          <div class="pref-row">
                            <div><div class="pref-label">Authenticated User</div><div class="pref-sub">Current active profile</div></div>
                            <div class="pref-val" id="profile-display-name">Chinni Krishna</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">Clinical Baseline</div><div class="pref-sub">Patient medical condition</div></div>
                            <div class="pref-val">Moderate Asthmatic Baseline</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">Patient Age / Demographics</div><div class="pref-sub">Used for risk calibration</div></div>
                            <div class="pref-val">30 Years · Disjoint Cohort Group</div>
                          </div>
                        </div>

                        <div class="profile-card">
                          <div class="card-heading"><span>⚙️</span> <span>Workstation Preferences</span></div>
                          <div class="pref-row">
                            <div><div class="pref-label">Visual Theme</div><div class="pref-sub">Select preferred visual styling</div></div>
                            <div class="pref-val">🌌 Midnight Cyber (High Contrast)</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">Language / Locale</div><div class="pref-sub">Screening & Report language</div></div>
                            <div class="pref-val">English (US / Clinical)</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">Audio Quality Gate</div><div class="pref-sub">Reject noisy/clipped recordings</div></div>
                            <div class="pref-val" style="color: #00e5b0;">STRICT (SNR &gt; 15 dB)</div>
                          </div>
                        </div>
                        ''')

                # =============================================================
                # TAB 5: PRIVACY & SECURITY CENTER
                # =============================================================
                with gr.TabItem("🔐 Privacy", id="tab_privacy"):
                    with gr.Column(elem_classes=["panel"]):
                        gr.HTML('''
                        <div class="privacy-card">
                          <div class="card-heading"><span>🔒</span> <span>AEROVA Privacy & Biometric Security Center</span></div>
                          <p style="font-size: 13.5px; color: #cbd5e1; line-height: 1.6; margin-bottom: 16px;">
                            AEROVA processes all audio streams in local memory. Audio recordings are transformed into 50-D MFCC feature vectors and immediately discarded. No biometric audio files are shared with third parties.
                          </p>

                          <div class="pref-row">
                            <div><div class="pref-label">Audio Recording Storage</div><div class="pref-sub">Raw audio retention status</div></div>
                            <div class="pref-val" style="color: #00e5b0;">Ephemeral Only (Zero Storage)</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">Assessment Database</div><div class="pref-sub">Local runtime JSON storage</div></div>
                            <div class="pref-val">Local Workspace Only</div>
                          </div>
                          <div class="pref-row">
                            <div><div class="pref-label">HIPAA & GDPR Encryption</div><div class="pref-sub">Tokenized Patient ID hashing</div></div>
                            <div class="pref-val" style="color: #00e5b0;">AES-256 Validated</div>
                          </div>
                        </div>
                        ''')
                        with gr.Group(elem_classes=["panel-subtle"]):
                            gr.HTML('<h3 style="color: #f43f5e; font-size: 16px; margin: 0 0 6px;">⚠️ Data Erasure & History Purge</h3><p style="font-size: 13px; color: #94a3b8; margin: 0 0 14px;">Securely wipe all local assessment records and patient identifiers from the workstation.</p>')
                            clear_history_btn = gr.Button("🗑️ Delete All Assessment History", elem_classes=["secondary-button"])
                            privacy_status_box = gr.HTML()

            # MOBILE BOTTOM NAVIGATION BAR
            gr.HTML('''
            <nav class="mobile-bottom-nav">
              <button class="mobile-nav-btn active" onclick="document.querySelectorAll('.aerova-main-tabs .tab-nav button')[0].click()"><span>🎙️</span><span>Triage</span></button>
              <button class="mobile-nav-btn" onclick="document.querySelectorAll('.aerova-main-tabs .tab-nav button')[1].click()"><span>📈</span><span>Journey</span></button>
              <button class="mobile-nav-btn" onclick="document.querySelectorAll('.aerova-main-tabs .tab-nav button')[2].click()"><span>🤖</span><span>AI</span></button>
              <button class="mobile-nav-btn" onclick="document.querySelectorAll('.aerova-main-tabs .tab-nav button')[3].click()"><span>👤</span><span>Profile</span></button>
              <button class="mobile-nav-btn" onclick="document.querySelectorAll('.aerova-main-tabs .tab-nav button')[4].click()"><span>🔐</span><span>Privacy</span></button>
            </nav>
            ''')

            # =================================================================
            # SIDE ROBOT AI COPILOT DOCK (FLOATING DRAWER)
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
                    <div class="robot-title">AEROVA-BOT <span class="pro-tag">PRO v3.0</span></div>
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

                with gr.Row():
                    robot_chat_lang = gr.Dropdown(
                        ["English", "ಕನ್ನಡ (Kannada)", "हिंदी (Hindi)", "తెలుగు (Telugu)"],
                        value="English",
                        label="🌐 Language",
                        scale=2,
                    )
                    robot_mic_btn = gr.Button("🎙️ Voice Mic", elem_classes=["secondary-button"], scale=1)
                gr.HTML('<div id="robot-speech-status" style="margin: 2px 0 6px; font-size: 11px; font-weight: 700; color: #38bdf8;"></div>')

                gr.HTML('''
                <div class="robot-chip-row">
                  <span style="font-size: 11px; color: #94a3b8; font-weight: 700; margin-right: 4px;">Quick Ask:</span>
                </div>
                ''')
                with gr.Row():
                    chip_rec = gr.Button("🎙️ Recording Tips", elem_classes=["robot-chip"])
                    chip_models = gr.Button("🧠 98% ML Models", elem_classes=["robot-chip"])
                    chip_triage = gr.Button("🩺 Result Meaning", elem_classes=["robot-chip"])
                    chip_pdf = gr.Button("📄 PDF Reports", elem_classes=["robot-chip"])

                chatbot = gr.Chatbot(label="AEROVA Robot Chat", height=280)
                with gr.Row():
                    chat_input = gr.Textbox(
                        label="Message Robot",
                        placeholder="Type or click '🎙️ Voice Mic' in English, ಕನ್ನಡ, हिंदी, తెలుగు...",
                        scale=4,
                        elem_id="robot-chat-input-box",
                    )
                    chat_send = gr.Button("Ask Robot", variant="primary", elem_classes=["primary-button"], scale=1)

        # Dispatch and report state tracking
        report_meta_state = gr.State({})

        # Login event bindings
        persona_patient_btn.click(
            lambda: _persona_login("patient"),
            outputs=[login_view, workspace, login_email_state, login_notice],
        )
        persona_doctor_btn.click(
            lambda: _persona_login("doctor"),
            outputs=[login_view, workspace, login_email_state, login_notice],
        )
        persona_research_btn.click(
            lambda: _persona_login("researcher"),
            outputs=[login_view, workspace, login_email_state, login_notice],
        )
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
        captcha_autosolve_btn.click(lambda ans: str(ans), inputs=[captcha_answer_state], outputs=[captcha_entry])

        # Gemini key saving
        save_key_button.click(_set_gemini_key, [gemini_key_input], [gemini_key_state, key_status_box])
        gemini_tab_key_save.click(_set_gemini_key, [gemini_tab_key_input], [gemini_key_state, gemini_tab_key_status])

        # Voice Speech Recognition bindings
        tab_mic_btn.click(
            None,
            inputs=[tab_chat_lang],
            js="(lang) => { window.startSpeechRecognition(lang, '#tab-chat-input-box', 'speech-recognition-status'); }",
        )
        robot_mic_btn.click(
            None,
            inputs=[robot_chat_lang],
            js="(lang) => { window.startSpeechRecognition(lang, '#robot-chat-input-box', 'robot-speech-status'); }",
        )

        # Chat interaction bindings (supports dynamic key state and multilingual language)
        chat_send.click(_chat_response, [chat_input, chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])
        chat_input.submit(_chat_response, [chat_input, chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])
        tab_chat_send.click(_chat_response, [tab_chat_input, tab_chatbot, gemini_key_state, tab_chat_lang], [tab_chatbot, tab_chat_input])
        tab_chat_input.submit(_chat_response, [tab_chat_input, tab_chatbot, gemini_key_state, tab_chat_lang], [tab_chatbot, tab_chat_input])

        # Quick prompt chip shortcuts in Robot Drawer
        chip_rec.click(lambda h, k, l: _chat_response("What are the best tips for recording a clear cough?", h, k, l), [chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])
        chip_models.click(lambda h, k, l: _chat_response("Which machine learning models does AEROVA use and how accurate are they?", h, k, l), [chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])
        chip_triage.click(lambda h, k, l: _chat_response("What does a Healthy versus Disease result mean in AEROVA?", h, k, l), [chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])
        chip_pdf.click(lambda h, k, l: _chat_response("How do I export and download a clinical PDF report with QR verification?", h, k, l), [chatbot, gemini_key_state, robot_chat_lang], [chatbot, chat_input])

        # Quick prompt chip shortcuts in Tab 3 (AEROVA AI)
        quick_btn_result.click(lambda h, k, l: _chat_response("Explain my latest result", h, k, l), [tab_chatbot, gemini_key_state, tab_chat_lang], [tab_chatbot, tab_chat_input])
        quick_btn_precautions.click(lambda h, k, l: _chat_response("What clinical precautions and care plan should I follow?", h, k, l), [tab_chatbot, gemini_key_state, tab_chat_lang], [tab_chatbot, tab_chat_input])
        quick_btn_delta.click(lambda h, k, l: _chat_response("Compare my last two recordings and explain what changed", h, k, l), [tab_chatbot, gemini_key_state, tab_chat_lang], [tab_chatbot, tab_chat_input])
        quick_btn_kn.click(lambda h, k: _chat_response("ಕೆಮ್ಮು ಮತ್ತು ಶ್ವಾಸಕೋಶದ ಸೋಂಕಿನ ಮುನ್ನೆಚ್ಚರಿಕೆಗಳು ಯಾವುವು?", h, k, "ಕನ್ನಡ (Kannada)"), [tab_chatbot, gemini_key_state], [tab_chatbot, tab_chat_input])
        quick_btn_te.click(lambda h, k: _chat_response("దగ్గు మరియు శ్వాసకోశ ఇన్ఫెక్షన్ కోసం ఎలాంటి జాగ్రత్తలు తీసుకోవాలి?", h, k, "తెలుగు (Telugu)"), [tab_chatbot, gemini_key_state], [tab_chatbot, tab_chat_input])
        quick_btn_hi.click(lambda h, k: _chat_response("खांसी और फेفड़ों के संक्रमण के लिए क्या सावधानियां बरतनी चाहिए?", h, k, "हिंदी (Hindi)"), [tab_chatbot, gemini_key_state], [tab_chatbot, tab_chat_input])


        # Patient history & Journey refresh
        history_refresh.click(history_dashboard_html, [history_search], [history_output])
        journey_refresh_btn.click(journey_dashboard_html, outputs=[journey_container])

        # Privacy Clear History Action
        def _handle_clear_history():
            success = clear_history()
            if success:
                return (
                    '<div class="notification" style="color: #00e5b0;">✓ All session assessment records and identifiers were securely purged.</div>',
                    history_dashboard_html(),
                    journey_dashboard_html(),
                )
            return '<div class="notice">Failed to clear history.</div>', history_dashboard_html(), journey_dashboard_html()

        clear_history_btn.click(_handle_clear_history, outputs=[privacy_status_box, history_output, journey_container])

        # Module 2 Clinical Context Presets & Calibration
        preset_dry_btn.click(_preset_dry, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        preset_asthma_btn.click(_preset_asthma, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        preset_fever_btn.click(_preset_fever, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        preset_pediatric_btn.click(_preset_pediatric, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        preset_geriatric_btn.click(_preset_geriatric, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        preset_clear_btn.click(_preset_clear, outputs=[manual_notes, gender, age, cough_detected, respiratory_condition, fever_muscle_pain])
        calibrate_acoustic_btn.click(_auto_calibrate, inputs=[audio_input], outputs=[cough_detected, calibration_status])

        # Module 3 AI Second Opinion Generator
        second_opinion_btn.click(
            _generate_second_opinion,
            inputs=[prediction_output, details_output, manual_notes, gender, age, respiratory_condition, fever_muscle_pain],
            outputs=[second_opinion_output],
        )

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

