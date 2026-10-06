import json

import pytest

from task_context_fakes import offline_context_guard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    with offline_context_guard(monkeypatch):
        yield


def api():
    from mokioclaw.dashboard import task_result_windows
    return task_result_windows


def store(**kwargs):
    return api().ResultWindowStore(("task", 1, "delegation"), max_bytes=kwargs.pop("max_bytes", 32 * 1024 * 1024),
                                  max_results=kwargs.pop("max_results", 32), **kwargs)


def publish(service, text="abc" * 10000, **result):
    module = api()
    reservation = service.reserve({"ok": True, "diff": text, **result}, {"diff": module.ResultSegment("text", text)})
    return service.commit(reservation, executed=True)


def next_cursor(page):
    return page["result_windows"]["diff"]["next_result_read"]["cursor"]


def test_cursor_only_reads_exposed_segment():
    service = store()
    page = service.first_page(publish(service), json_budget=16384)
    cursor = next_cursor(page)
    continued = service.read(cursor, 100, identity=("task", 1, "delegation"), json_budget=16384)
    assert continued["content"] == ("abc" * 10000)[continued["start"]:continued["end"]]
    assert len(continued["content"]) == 100
    assert continued == service.read(cursor, 100, identity=("task", 1, "delegation"), json_budget=16384)
    for forged in ("diff", "$.diff", cursor + "wrong"):
        with pytest.raises(api().ResultWindowError, match="^result_unavailable$"):
            service.read(forged, 1, identity=("task", 1, "delegation"), json_budget=16384)


def test_cursor_identity_and_eviction():
    service = store(max_results=1)
    cursor = next_cursor(service.first_page(publish(service), json_budget=16384))
    for identity in (("other", 1, "delegation"), ("task", 2, "delegation"), ("task", 1, "new")):
        with pytest.raises(api().ResultWindowError, match="^result_unavailable$"):
            service.read(cursor, 1, identity=identity, json_budget=16384)
    publish(service, "x" * 20000)
    with pytest.raises(api().ResultWindowError):
        service.read(cursor, 1, identity=("task", 1, "delegation"), json_budget=16384)
    service.clear()
    assert service.payload_bytes == 0 and service.cursor_count == 0


def test_page_json_and_body_limits():
    service = store()
    source = '中😀\"\n' * 8000
    page = service.first_page(publish(service, source), json_budget=9000)
    restored = page["diff"]
    assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 9000
    cursor = next_cursor(page)
    while cursor:
        page = service.read(cursor, 100000, identity=("task", 1, "delegation"), json_budget=9000)
        assert len(page["content"].encode()) <= 8192
        assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 9000
        assert page["end"] > page["start"]
        restored += page["content"]
        cursor = (page.get("next_result_read") or {}).get("cursor")
    assert restored == source


def test_reservation_cannot_publish_candidate_diff():
    service = store()
    module = api()
    candidate = service.reserve({"ok": True, "diff": "candidate"}, {"diff": module.ResultSegment("text", "candidate")})
    with pytest.raises(module.ResultWindowError):
        service.first_page(candidate, json_budget=16384)
    with pytest.raises(module.ResultWindowError):
        service.commit(candidate, executed=False)
    service.abort(candidate)
    assert service.payload_bytes == 0


def test_result_capacity_keeps_required_failure():
    module = api()
    service = store(max_results=1)
    reservation = service.reserve({"ok": False, "diff": "failed"},
                                  {"diff": module.ResultSegment("text", "failed")}, preserve_failure=True)
    failure = service.commit(reservation, executed=True)
    with pytest.raises(module.ResultWindowError, match="^result_capacity$"):
        publish(service)
    assert service.first_page(failure, json_budget=16384)["ok"] is False
    tiny = store(max_bytes=100)
    with pytest.raises(module.ResultWindowError, match="^result_capacity$"):
        publish(tiny)


def test_record_segments_are_copied_and_upstream_tail_is_explicit():
    module = api()
    service = store()
    records = tuple({"line": i, "text": "x" * 1000} for i in range(30))
    ref = service.commit(service.reserve({"ok": True, "matches": records, "upstream_complete": False},
                                        {"matches": module.ResultSegment("records", records)}), executed=True)
    records[0]["text"] = "changed"
    page = service.first_page(ref, json_budget=16384)
    assert page["matches"][0]["text"] != "changed"
    assert page["complete"] is False


def test_cursor_limit_and_fifo_are_bounded(monkeypatch):
    service = store(max_cursors=2)
    cursors = []
    for _ in range(3):
        cursors.append(next_cursor(service.first_page(publish(service), json_budget=16384)))
    assert service.cursor_count == 2
    with pytest.raises(api().ResultWindowError):
        service.read(cursors[0], 1, identity=("task", 1, "delegation"), json_budget=16384)
    for limit in (0, -1, True, "1"):
        with pytest.raises(api().ResultWindowError, match="^task_read_window_invalid$"):
            service.read(cursors[-1], limit, identity=("task", 1, "delegation"), json_budget=16384)


def test_multi_segment_total_body_is_bounded():
    module = api()
    service = store()
    result = {"ok": True, "stdout": "x" * 20000, "stderr": "y" * 20000}
    segments = {name: module.ResultSegment("text", result[name]) for name in ("stdout", "stderr")}
    ref = service.commit(service.reserve(result, segments), executed=True)
    page = service.first_page(ref, json_budget=16384)
    total_body_bytes = len(page["stdout"].encode()) + len(page["stderr"].encode())
    assert total_body_bytes <= 8192
    assert page["stdout"] and page["stderr"]


def test_multi_segment_reserves_json_progress_before_first_fill():
    module = api()
    service = store()
    result = {"ok": True, "stdout": "\u0000" * 20000, "stderr": "😀" * 20000}
    segments = {name: module.ResultSegment("text", result[name]) for name in ("stdout", "stderr")}
    reservation = service.reserve(result, segments)
    service.preview(reservation, json_budget=3000)
    assert service.cursor_count == 0
    ref = service.commit(reservation, executed=True)
    page = service.first_page(ref, json_budget=3000)
    assert page["stdout"] and page["stderr"]
    assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 3000
    for name in segments:
        restored = page[name]
        cursor = page["result_windows"][name]["next_result_read"]["cursor"]
        while cursor:
            continued = service.read(cursor, 100000, identity=service.identity, json_budget=3000)
            assert continued["end"] > continued["start"]
            restored += continued["content"]
            cursor = (continued.get("next_result_read") or {}).get("cursor")
        assert restored == result[name]
