import unittest
from unittest.mock import Mock, patch

import requests

from frontend_ui import _gemini_answer


class GeminiConnectionTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("frontend_ui.requests.post")
    def test_missing_key_does_not_send_request(self, post):
        with self.assertLogs("aerova.gemini", level="WARNING") as logs:
            self.assertIsNone(_gemini_answer("Hello", []))
        post.assert_not_called()
        self.assertIn("GEMINI_API_KEY", logs.output[0])

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "models/gemini-2.5-flash"}, clear=True)
    @patch("frontend_ui.requests.post")
    def test_google_key_and_model_resource_name(self, post):
        post.return_value.json.return_value = {
            "candidates": [{"content": {"parts": [
                {"text": "Thought", "thought": True}, {"text": "Hello!"}
            ]}}]
        }
        self.assertEqual(_gemini_answer("Hi", []), "Hello!")
        self.assertTrue(post.call_args.args[0].endswith("/models/gemini-2.5-flash:generateContent"))
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        config = post.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(config["thinkingConfig"]["thinkingBudget"], 0)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "secret-key"}, clear=True)
    @patch("frontend_ui.requests.post")
    def test_http_errors_are_actionable_without_logging_secrets(self, post):
        for status, expected in [(400, "configuration"), (403, "permissions"), (404, "GEMINI_MODEL"), (429, "quota")]:
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                post.return_value.raise_for_status.side_effect = requests.HTTPError(
                    "secret-key sensitive response", response=response
                )
                with self.assertLogs("aerova.gemini", level="WARNING") as logs:
                    self.assertIsNone(_gemini_answer("private question", []))
                self.assertIn(expected, logs.output[0])
                self.assertNotIn("secret-key", str(logs.output))
                self.assertNotIn("private question", str(logs.output))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("frontend_ui.requests.post")
    def test_timeout_and_empty_responses_fall_back(self, post):
        post.side_effect = requests.Timeout("sensitive request details")
        with self.assertLogs("aerova.gemini", level="WARNING"):
            self.assertIsNone(_gemini_answer("Hello", []))
        post.side_effect = None
        for payload in [{}, {"candidates": []}, {"candidates": [{"content": {"parts": []}}]}]:
            post.return_value.json.return_value = payload
            with self.assertLogs("aerova.gemini", level="WARNING"):
                self.assertIsNone(_gemini_answer("Hello", []))


if __name__ == "__main__":
    unittest.main()
