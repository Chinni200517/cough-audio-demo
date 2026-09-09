import unittest

from prediction_utils import build_prediction_result


class PredictionUtilsTests(unittest.TestCase):
    def test_healthy_when_no_risk_signals(self):
        result = build_prediction_result(
            prediction=0,
            probability=0.10,
            notes="no symptoms",
            respiratory_condition=False,
            fever_muscle_pain=False,
        )
        self.assertEqual(result["final_classification"], "Healthy / normal")
        self.assertEqual(result["sound_classification"], "Healthy / normal sound")

    def test_symptoms_raise_final_risk(self):
        result = build_prediction_result(
            prediction=1,
            probability=0.72,
            notes="fever and body pain",
            respiratory_condition=True,
            fever_muscle_pain=True,
        )
        self.assertIn("Possible", result["final_classification"])
        self.assertEqual(result["symptom_classification"], "Possible viral infection")

    def test_emergency_signs_override_healthy_audio_result(self):
        result = build_prediction_result(
            prediction=0,
            probability=0.95,
            notes="gasping and blue lips with severe chest tightness",
        )
        self.assertEqual(result["status"], "urgent")
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["final_classification"], "Urgent medical attention needed")
        self.assertIn("emergency care now", result["recommendation"])


if __name__ == "__main__":
    unittest.main()
