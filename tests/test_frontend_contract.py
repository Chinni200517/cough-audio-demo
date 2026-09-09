import unittest
import json
from unittest.mock import Mock, patch

import gradio_app
from frontend_ui import _chat_response, _run_prediction


class FrontendContractTests(unittest.TestCase):
    def test_best_saved_model_is_compatible_and_highest_scoring(self):
        preprocessor = gradio_app.load_preprocessor()
        models = gradio_app.compatible_model_files(preprocessor, gradio_app.list_available_models())
        best = gradio_app.choose_best_model(models)
        self.assertIn(best, models)
        with open("output/models_summary.json", encoding="utf-8") as summary_file:
            summary = json.load(summary_file)
        best_score = summary[best.removesuffix(".joblib")]["accuracy"]
        self.assertEqual(best_score, max(item["accuracy"] for item in summary.values() if item.get("accuracy") is not None))

    def test_report_email_contains_login_recipient_and_fallback_file(self):
        payload = _run_prediction(
            lambda *args: ("<div>Healthy</div>", "<div>Low risk</div>"),
            "person@example.com",
            None,
            None,
            "",
            "",
            "extra_trees.joblib",
            "unknown",
            30,
            0.5,
            "false",
            "false",
        )
        result, details = payload[:2]
        self.assertIn("mailto:person%40example.com", details)
        self.assertIn("Download email file", details)
        self.assertIn("Healthy", details)

    @patch.dict("os.environ", {"Gemini_API_Key": "test-key"}, clear=True)
    @patch("frontend_ui.requests.post")
    def test_chat_uses_gemini_for_general_questions(self, post):
        response = Mock()
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Gemini-generated answer."}]}}]
        }
        post.return_value = response

        history, cleared = _chat_response("What should I know about hydration?", [])

        self.assertEqual(cleared, "")
        self.assertEqual(history[-1]["role"], "assistant")
        self.assertEqual(history[-1]["content"], "Gemini-generated answer.")
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertIn(
            "Chinni200517",
            post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"],
        )


if __name__ == "__main__":
    unittest.main()
