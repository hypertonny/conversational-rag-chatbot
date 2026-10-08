"""Light tests for UnifierClient request construction (no network)."""
from unifier_client import UnifierClient


def test_headers_include_bearer_token():
    c = UnifierClient(bearer_token="abc123")
    headers = c._get_headers()
    assert headers["Authorization"] == "Bearer abc123"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_custom_headers_merge():
    c = UnifierClient(bearer_token="t")
    headers = c._get_headers({"X-Trace": "1"})
    assert headers["X-Trace"] == "1"
    assert headers["Authorization"] == "Bearer t"


def test_base_url_defaults_and_strips_trailing_slash():
    assert UnifierClient(bearer_token="t").base_url == UnifierClient.DEFAULT_BASE_URL
    c = UnifierClient(bearer_token="t", base_url="https://example.com/api/")
    assert c.base_url == "https://example.com/api"


def test_test_connection_requires_token():
    ok, msg, code = UnifierClient(bearer_token="").test_connection()
    assert ok is False
    assert code == 0
