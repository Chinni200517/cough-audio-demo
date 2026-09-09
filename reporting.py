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
RUNTIME_DIR = BASE_DIR / "runtime"
HISTORY_PATH = RUNTIME_DIR / "assessment_history.json"
_HISTORY_LOCK = threading.Lock()


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def save_assessment(entry: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with _HISTORY_LOCK:
        history = []
        if HISTORY_PATH.exists():
            try:
                history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                history = []
        history.insert(0, entry)
        temp_path = HISTORY_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(history[:200], indent=2), encoding="utf-8")
        os.replace(temp_path, HISTORY_PATH)


def load_history() -> list[dict]:
    with _HISTORY_LOCK:
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            return []


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

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    fd, pdf_path = tempfile.mkstemp(prefix=f"aerova-{patient_id.lower()}-", suffix=".pdf", dir=RUNTIME_DIR)
    os.close(fd)
    verification_text = f"AEROVA report|{patient_id}|{label}|{confidence:.4f}|{datetime.now():%Y-%m-%d}"
    qr = qrcode.make(verification_text)
    qr_fd, qr_path = tempfile.mkstemp(suffix=".png", dir=RUNTIME_DIR)
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
