import unittest
from unittest.mock import Mock, patch

import requests

from frontend_ui import _gemini_answer, _gemini_fallback_models


class GeminiConnectionTests(unittest.TestCase):
    def setUp(self):
        _gemini_fallback_models.cache_clear()

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
    @patch("frontend_ui.requests.get")
    @patch("frontend_ui.requests.post")
    def test_http_errors_are_actionable_without_logging_secrets(self, post, get):
        get.return_value.json.return_value = {"models": []}
        for status, expected in [(400, "configuration"), (403, "permissions"), (404, "GEMINI_MODEL"), (429, "quota")]:
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                post.return_value.raise_for_status.side_effect = requests.HTTPError(
                    "secret-key sensitive response", response=response
                )
                post.return_value.status_code = status
                with self.assertLogs("aerova.gemini", level="WARNING") as logs:
                    self.assertIsNone(_gemini_answer("private question", []))
                self.assertIn(expected, logs.output[0])
                self.assertNotIn("secret-key", str(logs.output))
                self.assertNotIn("private question", str(logs.output))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("frontend_ui.requests.get")
    @patch("frontend_ui.requests.post")
    def test_missing_model_discovers_and_uses_available_chat_model(self, post, get):
        missing = requests.Response()
        missing.status_code = 404
        success = Mock()
        success.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Paris."}]}}]}
        post.side_effect = [missing, success]
        get.return_value.json.return_value = {"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-pro", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-9-flash-lite", "supportedGenerationMethods": ["embedContent"]},
        ]}
        with self.assertLogs("aerova.gemini", level="WARNING"):
            self.assertEqual(_gemini_answer("Capital of France?", []), "Paris.")
        self.assertEqual(post.call_count, 2)
        self.assertTrue(post.call_args.args[0].endswith("/gemini-3.1-flash-lite:generateContent"))
        self.assertNotIn("thinkingConfig", post.call_args.kwargs["json"]["generationConfig"])
        self.assertEqual(get.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("frontend_ui.requests.get")
    @patch("frontend_ui.requests.post")
    def test_quota_error_does_not_switch_models(self, post, get):
        response = requests.Response()
        response.status_code = 429
        post.return_value = response
        with self.assertLogs("aerova.gemini", level="WARNING"):
            self.assertIsNone(_gemini_answer("Hello", []))
        get.assert_not_called()
        self.assertEqual(post.call_count, 1)

    @patch("frontend_ui.requests.get")
    def test_discovery_paginates_and_caches(self, get):
        first, second = Mock(), Mock()
        first.json.return_value = {"models": [], "nextPageToken": "next"}
        second.json.return_value = {"models": [{"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]}
        get.side_effect = [first, second]
        self.assertEqual(_gemini_fallback_models("test-key", 1), ("gemini-2.5-flash-lite",))
        self.assertEqual(_gemini_fallback_models("test-key", 1), ("gemini-2.5-flash-lite",))
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs["params"]["pageToken"], "next")

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("frontend_ui.requests.get")
    @patch("frontend_ui.requests.post")
    def test_unavailable_fallbacks_stop_after_two_alternatives(self, post, get):
        response = requests.Response()
        response.status_code = 404
        post.return_value = response
        get.return_value.json.return_value = {"models": [
            {"name": f"models/gemini-{version}-flash-lite", "supportedGenerationMethods": ["generateContent"]}
            for version in ["2.5", "3.1", "3.5"]
        ]}
        with self.assertLogs("aerova.gemini", level="WARNING"):
            self.assertIsNone(_gemini_answer("Hello", []))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(get.call_count, 1)

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
