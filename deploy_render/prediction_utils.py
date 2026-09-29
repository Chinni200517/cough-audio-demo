from html import escape
import re
from typing import List, Dict, Any


SYMPTOM_KEYWORDS = {
    "fever": ["fever", "high fever", "temperature", "hot"],
    "cough": ["cough", "coughing"],
    "breathing": ["shortness of breath", "breathing", "breath", "chest tightness"],
    "sore_throat": ["sore throat", "throat pain"],
    "body_pain": ["body pain", "muscle pain", "body ache", "joint pain"],
    "fatigue": ["fatigue", "tired", "weak", "exhausted"],
    "cold": ["cold", "runny nose", "congestion", "flu"],
    "chills": ["chills", "shivering"],
}

EMERGENCY_KEYWORDS = [
    "severe difficulty breathing",
    "difficulty breathing",
    "gasping",
    "unable to speak",
    "inability to speak",
    "blue lips",
    "blue skin",
    "grey lips",
    "gray lips",
    "grey skin",
    "gray skin",
    "sudden confusion",
    "severe chest tightness",
    "chest heaviness",
    "severe chest pain",
]


def _is_negated(text: str, match_start: int) -> bool:
    """Check if a matched symptom keyword is preceded by negation in the same sentence or clause."""
    prefix = text[:match_start]
    last_boundary = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind(","), 0)
    clause = prefix[last_boundary:].lower()
    negation_patterns = [
        r"\bno\b",
        r"\bnot\b",
        r"\bnone\b",
        r"\bdenies\b",
        r"\bdenied\b",
        r"\bwithout\b",
        r"\bnegative\s+for\b",
        r"\bfree\s+of\b",
        r"\bclear\s+of\b",
        r"\babsence\s+of\b",
        r"\bnever\b",
        r"\bzero\b",
    ]
    for pattern in negation_patterns:
        if re.search(pattern, clause):
            return True
    return False


def _contains_any(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        start = 0
        while True:
            idx = lowered.find(kw_lower, start)
            if idx == -1:
                break
            if not _is_negated(lowered, idx):
                return True
            start = idx + len(kw_lower)
    return False


def detect_emergency_signs(notes: str) -> List[str]:
    text = notes or ""
    labels = {
        "breathing emergency": ["severe difficulty breathing", "difficulty breathing", "gasping", "unable to speak", "inability to speak"],
        "blue/grey lips or skin": ["blue lips", "blue skin", "grey lips", "gray lips", "grey skin", "gray skin"],
        "sudden confusion": ["sudden confusion"],
        "severe chest tightness/heaviness": ["severe chest tightness", "chest heaviness", "severe chest pain"],
    }
    return sorted(label for label, keywords in labels.items() if _contains_any(text, keywords))


def detect_symptoms(notes: str, respiratory_condition: bool = False, fever_muscle_pain: bool = False) -> List[str]:
    text = notes or ""
    found = []
    if fever_muscle_pain:
        found.append("fever/body pain")
    if respiratory_condition:
        found.append("respiratory condition")
    for symptom_name, keywords in SYMPTOM_KEYWORDS.items():
        if _contains_any(text, keywords):
            found.append(symptom_name)
    return sorted(set(found))


def classify_sound(prediction: int, probability: float) -> str:
    if prediction == 0 and probability < 0.40:
        return "Healthy / normal sound"
    if prediction == 0:
        return "Mostly healthy sound with mild uncertainty"
    if probability >= 0.75:
        return "Strong abnormal respiratory sound"
    if probability >= 0.50:
        return "Moderate abnormal respiratory sound"
    return "Acoustic sound evaluated"


def classify_symptoms(notes: str, respiratory_condition: bool = False, fever_muscle_pain: bool = False) -> str:
    symptoms = detect_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    if not symptoms:
        return "No major symptoms reported"
    if "fever/body pain" in symptoms or "cold" in symptoms or "fatigue" in symptoms or "chills" in symptoms:
        return "Possible viral infection"
    if "breathing" in symptoms or "respiratory condition" in symptoms or "cough" in symptoms:
        return "Possible respiratory illness"
    return "Symptoms reported"


def diagnose_condition_and_precautions(
    prediction: int,
    probability: float,
    notes: str = "",
    respiratory_condition: bool = False,
    fever_muscle_pain: bool = False,
    age: float = 35.0,
) -> Dict[str, Any]:
    """Diagnose disease condition and generate structured clinical precautions."""
    text = (notes or "").lower()
    emergency_signs = detect_emergency_signs(notes)

    explicit_healthy = any(
        h in text for h in [
            "healthy", "normal", "asymptomatic", "clear breath", "clear lung",
            "no symptom", "no illness", "routine check", "baseline"
        ]
    )

    has_fever_covid = fever_muscle_pain or _contains_any(text, ["covid", "fever", "chills", "high temperature", "myalgia"])
    has_respiratory = respiratory_condition or _contains_any(text, ["asthma", "wheezing", "wheez", "whistle", "dyspnea", "stridor"])
    has_productive = _contains_any(text, ["phlegm", "productive cough", "mucus", "green sputum", "yellow sputum", "pneumonia"])
    has_copd = (age >= 60 and (respiratory_condition or _contains_any(text, ["copd", "smoker", "chronic bronchitis", "emphysema"])))
    has_throat = _contains_any(text, ["sore throat", "strep", "hoarse voice", "barking cough", "influenza"])

    # Audio-First Determination: Recording acoustics decide disease vs healthy
    is_acoustic_disease = (prediction == 1 or probability >= 0.50)

    if emergency_signs:
        disease_name = "Disease"
        disease_tag = "DISEASE"
        severity = "Urgent / Life-Threatening"
        is_disease = True
        risk_level = "high"
        status_label = "Disease"
        precautions = [
            ("🚨 Call Emergency Services Immediately", "Dial your local emergency number (112 / 911 / 108) without delay. Do not wait for symptoms to subside."),
            ("🫁 Maintain Upright Seated Posture", "Sit upright leaning slightly forward (tripod position) to maximize thoracic lung expansion."),
            ("💨 Administer Oxygen / Rescue Bronchodilator", "If prescribed, administer emergency rescue inhaler (Salbutamol) via spacer."),
            ("🚫 Avoid Heavy Physical Movement", "Remain completely still and calm to minimize cellular oxygen consumption."),
        ]
    elif is_acoustic_disease:
        disease_name = "Disease"
        disease_tag = "DISEASE"
        severity = "Elevated Acoustic Risk"
        is_disease = True
        risk_level = "high" if probability >= 0.70 else "medium"
        status_label = "Disease"
        if has_fever_covid:
            precautions = [
                ("😷 Strict Isolation & Masking", "Isolate in a well-ventilated room. Wear a properly fitted N95/FFP2 respirator around others."),
                ("📊 Continuous Pulse Oximetry (SpO2)", "Check peripheral blood oxygen saturation every 4 hours. If SpO2 drops below 94%, seek urgent hospital evaluation."),
                ("🌡️ Antipyretic & Fever Protocol", "Monitor body temperature. Maintain adequate hydration with electrolyte-balanced fluids (2.5L–3.0L daily)."),
                ("💧 Saline Steam Inhalation", "Perform warm steam inhalation twice daily to soothe irritated bronchial mucous membranes."),
                ("👨‍⚕️ Clinical Consultation", "Schedule an evaluation with a certified medical doctor for confirmatory clinical testing."),
            ]
        elif has_respiratory:
            precautions = [
                ("🫁 Use Prescribed Bronchodilator Inhaler", "Take your prescribed beta-2 agonist inhaler with a spacer as directed by your physician."),
                ("🚫 Eliminate Environmental Triggers", "Stay away from cold air, vehicle exhaust smog, active/passive cigarette smoke, dust mites, and pet dander."),
                ("📈 Monitor Peak Expiratory Flow (PEF)", "Record PEF meter readings if available. A drop below 80% of personal best indicates airway constriction."),
                ("🪑 Elevated Sleeping Elevation", "Sleep with head and chest elevated at 30–45 degrees to prevent nocturnal airway obstruction."),
            ]
        elif has_productive:
            precautions = [
                ("🏥 Pulmonologist / Physician Chest Auscultation", "Undergo comprehensive physical chest examination; a chest X-ray or evaluation may be required."),
                ("💧 Airway Clearance & Mucolytics", "Maintain high warm fluid intake to thin bronchial mucus secretions. Avoid suppressing productive coughs."),
                ("📊 Monitor SpO2 and Respiratory Rate", "A resting respiratory rate exceeding 24 breaths/minute indicates increased work of breathing."),
                ("💊 Complete Full Prescribed Medication Course", "Take all prescribed medications exactly on schedule."),
            ]
        elif has_copd:
            precautions = [
                ("🫁 Dual Bronchodilator Maintenance", "Continue regular prescribed maintenance inhalers as scheduled."),
                ("🌬️ Pursed-Lip Breathing Technique", "Inhale through nose for 2 seconds, exhale slowly through pursed lips for 4 seconds to reduce air trapping."),
                ("😷 Urban Particulate Protection", "Avoid outdoor exposure during peak traffic hours; wear an N95 mask in areas with high air pollution."),
                ("📊 Baseline SpO2 Monitoring", "Maintain resting oxygen saturation monitoring as advised by your healthcare provider."),
            ]
        else:
            precautions = [
                ("🩺 Clinical Pulmonology Consultation", "The bioacoustic waveform demonstrates turbulence characteristic of respiratory irritation."),
                ("📊 Check Baseline Oxygen & Temperature", "Measure resting oxygen saturation and monitor for fever spikes over the next 48 hours."),
                ("😷 Wear Face Mask in Public", "Use a face mask in shared spaces until clinical evaluation rules out contagious infection."),
                ("💧 Optimize Airway Hydration", "Drink plenty of warm water and avoid dry, dusty, or unventilated environments."),
            ]
    else:
        disease_name = "Healthy"
        disease_tag = "HEALTHY"
        severity = "Normal / Non-Pathological"
        is_disease = False
        risk_level = "low"
        status_label = "Healthy"
        precautions = [
            ("✅ Maintain Respiratory Wellness", "Acoustic envelope demonstrates normal laminar airflow and clear vocal resonance."),
            ("🏃 Routine Aerobic Exercise", "Continue regular physical exercise to maintain healthy alveolar capacity and cardiovascular endurance."),
            ("💧 Daily Hydration Baseline", "Consume 2 to 3 liters of water daily to maintain mucosal barrier integrity."),
            ("🌳 Clean Air Practices", "Enjoy outdoor activity in low-pollution environments (AQI < 50)."),
        ]

    precautions_items = "".join(
        f'''<div style="background: rgba(12, 34, 51, 0.85); border: 1px solid rgba(56, 189, 248, 0.2); border-left: 4px solid {'#f43f5e' if is_disease else '#00e5b0'}; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
          <div style="font-weight: 700; color: {'#fda4af' if is_disease else '#7bf5d4'}; font-size: 13px; margin-bottom: 3px;">{escape(title)}</div>
          <div style="color: #cbd5e1; font-size: 12.5px; line-height: 1.5;">{escape(body)}</div>
        </div>'''
        for title, body in precautions
    )

    badge_bg = "rgba(244, 63, 94, 0.18)" if is_disease else "rgba(0, 229, 176, 0.18)"
    badge_border = "#f43f5e" if is_disease else "#00e5b0"
    badge_color = "#fda4af" if is_disease else "#6ee7b7"

    precautions_card_html = f'''
    <div class="precautions-card" style="margin-top: 14px; background: rgba(7, 24, 38, 0.95); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 14px; padding: 18px 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 18px;">{'🚨' if is_disease else '🩺'}</span>
          <span style="font-size: 13px; font-weight: 800; color: #38bdf8; letter-spacing: 0.05em; text-transform: uppercase;">Clinical Precautions & Care Plan</span>
        </div>
        <span style="background: {badge_bg}; border: 1px solid {badge_border}; color: {badge_color}; font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 999px;">
          {escape(disease_tag)}
        </span>
      </div>
      <div style="margin-bottom: 12px;">
        <span style="color: #94a3b8; font-size: 12px;">Diagnosed Condition / Differential:</span>
        <div style="font-size: 15px; font-weight: 800; color: {'#f87171' if is_disease else '#34d399'}; margin-top: 2px;">{escape(disease_name)}</div>
        <div style="font-size: 11.5px; color: #94a3b8;">Severity Classification: <b>{escape(severity)}</b></div>
      </div>
      <div style="margin-top: 10px;">
        <div style="font-size: 11.5px; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;">Recommended Clinical Actions:</div>
        {precautions_items}
      </div>
    </div>
    '''

    return {
        "is_disease": is_disease,
        "disease_name": disease_name,
        "disease_tag": disease_tag,
        "severity": severity,
        "risk_level": risk_level,
        "status_label": status_label,
        "precautions": precautions,
        "precautions_html": precautions_card_html,
    }


def build_prediction_result(
    prediction: int,
    probability: float,
    notes: str = "",
    respiratory_condition: bool = False,
    fever_muscle_pain: bool = False,
    age: float = 35.0,
) -> Dict[str, Any]:
    sound_classification = classify_sound(prediction, probability)
    symptom_classification = classify_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    symptoms = detect_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    emergency_signs = detect_emergency_signs(notes)

    diag = diagnose_condition_and_precautions(
        prediction=prediction,
        probability=probability,
        notes=notes,
        respiratory_condition=respiratory_condition,
        fever_muscle_pain=fever_muscle_pain,
        age=age,
    )

    if emergency_signs:
        return {
            "prediction": 1,
            "status": "urgent",
            "is_disease": True,
            "disease_name": diag["disease_name"],
            "sound_classification": sound_classification,
            "symptom_classification": "Emergency warning signs reported",
            "final_classification": "Urgent medical attention needed",
            "risk_level": "high",
            "confidence": float(probability),
            "symptoms_detected": emergency_signs + symptoms,
            "recommendation": "Call your local emergency number or seek emergency care now. Do not rely on this screening result, especially if breathing is difficult.",
            "precautions_html": diag["precautions_html"],
        }

    is_disease = diag["is_disease"]
    final_classification = f"Possible {diag['disease_name']}" if is_disease else "Healthy / normal"
    recommendation = (
        "Audio and clinical symptoms suggest abnormal acoustic markers consistent with " + diag["disease_name"] + ". Please consult a medical professional for evaluation."
        if is_disease
        else "No obvious abnormal sound or symptom pattern detected. Continue routine monitoring."
    )

    return {
        "prediction": 1 if is_disease else 0,
        "status": "covid-19" if is_disease else "healthy",
        "is_disease": is_disease,
        "disease_name": diag["disease_name"],
        "sound_classification": sound_classification,
        "symptom_classification": symptom_classification,
        "final_classification": final_classification,
        "risk_level": diag["risk_level"],
        "confidence": float(probability),
        "symptoms_detected": symptoms or ["No symptoms reported"],
        "recommendation": recommendation,
        "precautions_html": diag["precautions_html"],
    }
