"""Safe startup diagnostics for the deployed AEROVA demo.

This file only logs Gemini HTTP status codes/errors. It never logs API keys,
request headers, request bodies, or response bodies.
"""

try:
    import requests

    _original_request = requests.sessions.Session.request

    def _aerova_request(self, method, url, **kwargs):
        if "generativelanguage.googleapis.com" not in str(url):
            return _original_request(self, method, url, **kwargs)

        try:
            response = _original_request(self, method, url, **kwargs)
            print(f"[AEROVA Gemini] HTTP {response.status_code} model-request completed")
            return response
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            print(
                f"[AEROVA Gemini] request failed: "
                f"HTTP {status if status is not None else 'network'} {type(exc).__name__}"
            )
            raise

    requests.sessions.Session.request = _aerova_request
    print("[AEROVA Gemini] diagnostics enabled (API key hidden)")
except Exception as exc:
    print(f"[AEROVA Gemini] diagnostics could not start: {type(exc).__name__}")
