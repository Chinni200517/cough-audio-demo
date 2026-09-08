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


def _contains_any(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


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
    if prediction == 0 and probability < 0.35:
        return "Healthy / normal sound"
    if prediction == 0:
        return "Mostly healthy sound with mild uncertainty"
    if probability >= 0.75:
        return "Strong abnormal respiratory sound"
    if probability >= 0.55:
        return "Moderate abnormal respiratory sound"
    return "Possible abnormal respiratory sound"


def classify_symptoms(notes: str, respiratory_condition: bool = False, fever_muscle_pain: bool = False) -> str:
    symptoms = detect_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    if not symptoms:
        return "No major symptoms reported"
    if "fever/body pain" in symptoms or "cold" in symptoms or "fatigue" in symptoms or "chills" in symptoms:
        return "Possible viral infection"
    if "breathing" in symptoms or "respiratory condition" in symptoms or "cough" in symptoms:
        return "Possible respiratory illness"
    return "Symptoms reported"


def build_prediction_result(
    prediction: int,
    probability: float,
    notes: str = "",
    respiratory_condition: bool = False,
    fever_muscle_pain: bool = False,
) -> Dict[str, Any]:
    sound_classification = classify_sound(prediction, probability)
    symptom_classification = classify_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    symptoms = detect_symptoms(notes, respiratory_condition=respiratory_condition, fever_muscle_pain=fever_muscle_pain)
    emergency_signs = detect_emergency_signs(notes)

    if emergency_signs:
        return {
            "prediction": int(prediction),
            "status": "urgent",
            "sound_classification": sound_classification,
            "symptom_classification": "Emergency warning signs reported",
            "final_classification": "Urgent medical attention needed",
            "risk_level": "high",
            "confidence": float(probability),
            "symptoms_detected": emergency_signs + symptoms,
            "recommendation": "Call your local emergency number or seek emergency care now. Do not rely on this screening result, especially if breathing is difficult.",
        }

    if prediction == 0 and not symptoms:
        final_classification = "Healthy / normal"
        recommendation = "No obvious abnormal sound or symptom pattern detected. Continue routine monitoring."
        risk_level = "low"
    elif prediction == 0 and symptoms:
        final_classification = "Symptoms reported but audio looks mostly normal"
        recommendation = "Symptoms are present, so monitor closely and seek medical advice if they worsen."
        risk_level = "medium"
    elif prediction == 1 and symptoms:
        final_classification = "Possible respiratory issue / infection"
        recommendation = "Audio suggests abnormal sound and symptoms are present. Please consult a clinician for review."
        risk_level = "high"
    else:
        final_classification = "Possible abnormal sound"
        recommendation = "Audio suggests an abnormal sound. A medical review is recommended."
        risk_level = "medium"

    return {
        "prediction": int(prediction),
        "status": "covid-19" if prediction == 1 else "healthy",
        "sound_classification": sound_classification,
        "symptom_classification": symptom_classification,
        "final_classification": final_classification,
        "risk_level": risk_level,
        "confidence": float(probability),
        "symptoms_detected": symptoms,
        "recommendation": recommendation,
    }
