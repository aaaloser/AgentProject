import pytest

from mini_api.client import MiniClient


def test_old_positional_style_uses_default_options() -> None:
    calls = []

    def transport(path: str, timeout_seconds: float, retries: int):
        calls.append((path, timeout_seconds, retries))
        return {"ok": True}

    assert MiniClient(transport).request_json("/users") == {"ok": True}
    assert calls == [("/users", 2.0, 3)]


def test_explicit_timeout_and_retry_options_are_forwarded() -> None:
    calls = []

    def transport(path: str, timeout_seconds: float, retries: int):
        calls.append((path, timeout_seconds, retries))
        return {"ok": True}

    client = MiniClient(transport)
    assert client.request_json("/slow", timeout_seconds=0.25, retries=0) == {"ok": True}
    assert calls == [("/slow", 0.25, 0)]


def test_invalid_options_are_rejected() -> None:
    client = MiniClient(lambda *_: None)

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        client.request_json("/users", timeout_seconds=0)
    with pytest.raises(ValueError, match="retries cannot be negative"):
        client.request_json("/users", retries=-1)


def test_transport_exceptions_are_not_hidden() -> None:
    def failing_transport(*_args):
        raise RuntimeError("transport failed")

    with pytest.raises(RuntimeError, match="transport failed"):
        MiniClient(failing_transport).request_json("/users")
