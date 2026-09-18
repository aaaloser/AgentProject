from mini_api.client import MiniClient


def test_old_request_json_call_remains_compatible() -> None:
    calls = []

    def transport(path, timeout_seconds, retries):
        calls.append((path, timeout_seconds, retries))
        return {"ok": True}

    result = MiniClient(transport).request_json("/users")

    assert result == {"ok": True}
