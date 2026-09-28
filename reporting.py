"""PDF reporting and lightweight local assessment history for AEROVA."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from html import escape
from pathlib import Path

import qrcode


BASE_DIR = Path(__file__).resolve().parent


def get_runtime_dir() -> Path:
    """Return a directory guaranteed to be writable across Docker, Render, and local OS."""
    candidates = [
        BASE_DIR / "runtime",
        Path(tempfile.gettempdir()) / "aerova_runtime",
        Path(tempfile.gettempdir()),
    ]
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            test_file = cand / f".perm_check_{os.getpid()}"
            test_file.touch()
            test_file.unlink(missing_ok=True)
            return cand
        except Exception:
            continue
    return Path(tempfile.gettempdir())


RUNTIME_DIR = get_runtime_dir()
HISTORY_PATH = RUNTIME_DIR / "assessment_history.json"
_HISTORY_LOCK = threading.Lock()


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def save_assessment(entry: dict) -> None:
    target_dir = get_runtime_dir()
    history_path = target_dir / "assessment_history.json"
    with _HISTORY_LOCK:
        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                history = []
        history.insert(0, entry)
        try:
            temp_path = history_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(history[:200], indent=2), encoding="utf-8")
            os.replace(temp_path, history_path)
        except (PermissionError, OSError):
            fallback_path = Path(tempfile.gettempdir()) / "assessment_history.json"
            temp_path = fallback_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(history[:200], indent=2), encoding="utf-8")
            os.replace(temp_path, fallback_path)


def load_history() -> list[dict]:
    target_dir = get_runtime_dir()
    history_path = target_dir / "assessment_history.json"
    with _HISTORY_LOCK:
        for path in [history_path, Path(tempfile.gettempdir()) / "assessment_history.json"]:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        return data
                except (OSError, ValueError, TypeError):
                    continue
        return []


def clear_history() -> bool:
    """Securely purge stored session assessments."""
    target_dir = get_runtime_dir()
    history_path = target_dir / "assessment_history.json"
    fallback_path = Path(tempfile.gettempdir()) / "assessment_history.json"
    with _HISTORY_LOCK:
        try:
            if history_path.exists():
                history_path.write_text("[]", encoding="utf-8")
            if fallback_path.exists():
                fallback_path.write_text("[]", encoding="utf-8")
            return True
        except Exception:
            return False


def journey_dashboard_html(range_days: int = 7) -> str:
    """Render authentic longitudinal respiratory journey from recorded assessments."""
    history = load_history()
    if not history:
        return '''<div style="background: rgba(8, 22, 36, 0.7); border: 1px dashed rgba(56, 189, 248, 0.25); border-radius: 20px; padding: 40px 24px; text-align: center;">
          <div style="font-size: 48px; margin-bottom: 12px;">📈</div>
          <h3 style="color: #ffffff; font-size: 19px; font-weight: 800; margin-bottom: 6px;">Your Respiratory Journey</h3>
          <p style="color: #94a3b8; font-size: 14px; max-width: 500px; margin: 0 auto 16px auto; line-height: 1.5;">
            Your respiratory journey will appear after your first analysis. Every recorded session is analyzed for acoustic quality, energy stability, and clinical trend.
          </p>
          <div style="display: inline-flex; align-items: center; gap: 8px; background: rgba(0, 229, 176, 0.12); border: 1px solid rgba(0, 229, 176, 0.35); padding: 6px 16px; border-radius: 100px; color: #00e5b0; font-size: 12px; font-weight: 700;">
            <span>🎙️</span> <span>Record a cough in Step 1 to generate your baseline</span>
          </div>
        </div>'''

    count = len(history)
    high_risks = sum(str(h.get("risk", "")).lower() == "high" for h in history)
    avg_conf = sum(float(h.get("confidence", 0.8)) for h in history) / count * 100

    # Build timeline items from actual records
    timeline_rows = ""
    for idx, item in enumerate(history[:8]):
        pid = escape(str(item.get("patient_id", "—")))
        dt = escape(str(item.get("date", "—")))
        lbl = escape(str(item.get("label", "—")))
        rsk = escape(str(item.get("risk", "—")).title())
        conf = float(item.get("confidence", 0)) * 100
        risk_color = "#f43f5e" if "High" in rsk else ("#f59e0b" if "Med" in rsk else "#00e5b0")
        timeline_rows += f'''
        <div style="background: rgba(6, 21, 33, 0.8); border: 1px solid rgba(56, 189, 248, 0.18); border-radius: 14px; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px;">
          <div>
            <div style="font-size: 14px; font-weight: 800; color: #ffffff;">{pid} · <span style="color: #38bdf8;">{lbl}</span></div>
            <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">📅 {dt}</div>
          </div>
          <div style="text-align: right;">
            <span style="display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 800; text-transform: uppercase; background: rgba(255,255,255,0.06); color: {risk_color}; border: 1px solid {risk_color};">
              {rsk} Risk
            </span>
            <div style="font-size: 12px; font-weight: 700; color: #00e5b0; margin-top: 4px;">{conf:.1f}% Conf</div>
          </div>
        </div>
        '''

    # Comparison delta if at least 2 records exist
    comp_html = ""
    if len(history) >= 2:
        curr = history[0]
        prev = history[1]
        c_conf = float(curr.get("confidence", 0)) * 100
        p_conf = float(prev.get("confidence", 0)) * 100
        delta_conf = c_conf - p_conf
        delta_sign = "+" if delta_conf >= 0 else ""
        delta_color = "#00e5b0" if delta_conf >= 0 else "#f43f5e"

        comp_html = f'''
        <div style="background: rgba(6, 21, 33, 0.95); border: 1px solid var(--border-line); border-radius: 16px; padding: 18px; margin-top: 18px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <h4 style="font-size: 14px; font-weight: 800; color: #ffffff; margin: 0;">🔄 Delta: Latest vs Previous Session</h4>
            <span style="font-size: 11px; color: #94a3b8;">Authentic Historical Comparison</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center;">
            <div class="metric-item" style="padding: 10px;">
              <span class="metric-label">Latest ({escape(str(curr.get("patient_id", "—")))})</span>
              <span style="font-size: 15px; font-weight: 800; color: #00e5b0; display: block; margin-top: 4px;">{c_conf:.1f}% Conf</span>
            </div>
            <div class="metric-item" style="padding: 10px;">
              <span class="metric-label">Previous ({escape(str(prev.get("patient_id", "—")))})</span>
              <span style="font-size: 15px; font-weight: 800; color: #38bdf8; display: block; margin-top: 4px;">{p_conf:.1f}% Conf</span>
            </div>
            <div class="metric-item" style="padding: 10px;">
              <span class="metric-label">Confidence Delta</span>
              <span style="font-size: 15px; font-weight: 800; color: {delta_color}; display: block; margin-top: 4px;">{delta_sign}{delta_conf:.1f}%</span>
            </div>
          </div>
        </div>
        '''

    return f'''
    <div style="display: grid; gap: 16px;">
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center;">
        <div class="metric-item">
          <span class="metric-label">Analyzed Sessions</span>
          <span class="metric-value" style="color: #00e5b0;">{count}</span>
          <span class="metric-trend">● Real BioAcoustics</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Avg Confidence</span>
          <span class="metric-value" style="color: #38bdf8;">{avg_conf:.1f}%</span>
          <span class="metric-trend">Model Precision</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">High-Risk Events</span>
          <span class="metric-value" style="color: {"#f43f5e" if high_risks else "#00e5b0"};">{high_risks}</span>
          <span class="metric-trend">Clinical Flags</span>
        </div>
      </div>

      <div style="margin-top: 6px;">
        <div style="font-size: 12px; font-weight: 800; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">
          📈 Longitudinal Respiratory Assessments ({len(history)} total):
        </div>
        {timeline_rows}
      </div>

      {comp_html}
    </div>
    '''


def history_dashboard_html(query: str = "") -> str:
    history = load_history()
    needle = str(query or "").strip().lower()
    filtered = [item for item in history if needle in str(item.get("patient_id", "")).lower()] if needle else history
    high_risk = sum(str(item.get("risk", "")).lower() == "high" for item in history)
    disease = sum(str(item.get("label", "")).lower() not in {"healthy", "normal"} for item in history)
    rows = "".join(
        f'''<tr><td><b>{escape(str(item.get("patient_id", "—")))}</b></td>
        <td>{escape(str(item.get("date", "—")))}</td><td>{escape(str(item.get("label", "—")))}</td>
        <td>{escape(str(item.get("risk", "—")).title())}</td><td>{float(item.get("confidence", 0)) * 100:.1f}%</td></tr>'''
        for item in filtered[:10]
    ) or '<tr><td colspan="5" class="history-empty">No matching assessments yet.</td></tr>'
    return f'''<div class="history-dashboard">
      <div class="history-metrics">
        <div><span>Total assessments</span><strong>{len(history)}</strong></div>
        <div><span>Flagged results</span><strong>{disease}</strong></div>
        <div><span>High-risk cases</span><strong>{high_risk}</strong></div>
      </div>
      <div class="history-table-wrap"><table class="history-table">
        <thead><tr><th>Patient ID</th><th>Date</th><th>Readout</th><th>Risk</th><th>Confidence</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </div>'''



def create_pdf_report(
    *, patient_id: str, email: str, age, gender: str, result_html: str,
    details_html: str, model: str, confidence: float, label: str, risk: str,
    quality: dict, comparison: list[dict], chart_path: str | None,
) -> str:
    """Create a two-page, prescription-style PDF with a verification QR."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    target_dir = get_runtime_dir()
    try:
        fd, pdf_path = tempfile.mkstemp(prefix=f"aerova-{patient_id.lower()}-", suffix=".pdf", dir=str(target_dir))
    except (PermissionError, OSError):
        target_dir = Path(tempfile.gettempdir())
        fd, pdf_path = tempfile.mkstemp(prefix=f"aerova-{patient_id.lower()}-", suffix=".pdf", dir=str(target_dir))
    os.close(fd)
    verification_text = f"AEROVA report|{patient_id}|{label}|{confidence:.4f}|{datetime.now():%Y-%m-%d}"
    qr = qrcode.make(verification_text)
    try:
        qr_fd, qr_path = tempfile.mkstemp(suffix=".png", dir=str(target_dir))
    except (PermissionError, OSError):
        qr_fd, qr_path = tempfile.mkstemp(suffix=".png")
    os.close(qr_fd)
    qr.save(qr_path)

    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69), facecolor="#f4f8fa")
        ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
        ax.add_patch(plt.Rectangle((0, .86), 1, .14, color="#0d6075"))
        ax.text(.06, .95, "AEROVA", color="#bcecf2", fontsize=11, weight="bold")
        ax.text(.06, .895, "Respiratory Screening Report", color="white", fontsize=23, weight="bold")
        ax.text(.06, .81, f"Patient ID  {patient_id}", fontsize=12, weight="bold", color="#153448")
        ax.text(.55, .81, datetime.now().strftime("%d %B %Y, %I:%M %p"), fontsize=10, color="#526f7d")
        ax.text(.06, .765, f"Age: {age} years    Gender: {str(gender).title()}    Recipient: {email}", fontsize=10)
        ax.add_patch(plt.Rectangle((.06, .58), .88, .14, facecolor="#eaf6f8", edgecolor="#9bcbd4"))
        ax.text(.09, .68, "SCREENING READOUT", fontsize=9, weight="bold", color="#18788c")
        ax.text(.09, .625, label, fontsize=25, weight="bold", color="#153448")
        ax.text(.66, .63, f"{confidence * 100:.1f}% confidence", fontsize=12, weight="bold", color="#18788c")
        ax.text(.09, .59, f"Risk level: {str(risk).upper()}    Model: {model}", fontsize=10)
        ax.text(.06, .535, "Clinical summary", fontsize=12, weight="bold", color="#153448")
        ax.text(.06, .49, _plain(result_html + " " + details_html)[:850], fontsize=9, wrap=True, va="top", linespacing=1.5)
        ax.text(.06, .25, "Recording quality", fontsize=12, weight="bold")
        quality_text = (
            f"Status: {quality.get('status', 'unknown').title()}    Duration: {quality.get('duration', 0):.1f}s    "
            f"Signal level: {quality.get('dbfs', -100):.1f} dBFS    Clipping: {quality.get('clipping_ratio', 0) * 100:.2f}%"
        )
        ax.text(.06, .215, quality_text, fontsize=9)
        ax.text(.06, .145, "This report is a screening aid, not a medical diagnosis or prescription. Seek urgent care for severe breathing difficulty, chest pain, confusion, blue lips, or rapidly worsening symptoms.", fontsize=8.5, color="#754f2b", wrap=True)
        qr_image = mpimg.imread(qr_path)
        qr_ax = fig.add_axes([.78, .04, .14, .10]); qr_ax.imshow(qr_image); qr_ax.axis("off")
        ax.text(.06, .06, "Digitally generated by AEROVA", fontsize=9, weight="bold", color="#0d6075")
        ax.text(.06, .035, "Scan the QR code to verify the report identity and recorded outcome.", fontsize=7.5, color="#607985")
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        if chart_path and os.path.exists(chart_path):
            fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
            ax = fig.add_axes([.06, .08, .88, .84]); ax.axis("off")
            ax.text(0, 1.04, "Explainability and model comparison", transform=ax.transAxes, fontsize=19, weight="bold", color="#153448")
            ax.imshow(mpimg.imread(chart_path)); ax.set_aspect("auto")
            rows = comparison[:9]
            table_text = "\n".join(f"{row['model']}: {row['label']} ({row['confidence'] * 100:.1f}%)" for row in rows)
            ax.text(0, -.05, table_text, transform=ax.transAxes, fontsize=8, va="top")
            pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)
    try:
        os.remove(qr_path)
    except OSError:
        pass
    return pdf_path
