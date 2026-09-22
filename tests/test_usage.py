from mokioclaw.providers.usage import (
    start_usage_collection,
    sum_usage,
    current_usage_handler,
)
from mokioclaw.providers.call_journal import CallJournal


class FakeResponse:
    def __init__(self, token_usage):
        self.llm_output = {"token_usage": token_usage} if token_usage else {}


def test_handler_aggregates_only_within_collection_scope() -> None:
    handler = current_usage_handler()
    handler.on_llm_end(FakeResponse({"prompt_tokens": 10, "completion_tokens": 4}))  # outside scope: ignored

    records = start_usage_collection()
    handler.on_llm_end(FakeResponse({"prompt_tokens": 10, "completion_tokens": 4}))
    handler.on_llm_end(FakeResponse({"prompt_tokens": 5, "completion_tokens": 1}))
    handler.on_llm_end(FakeResponse(None))  # no usage reported: skipped

    assert records == [
        {"input_tokens": 10, "output_tokens": 4},
        {"input_tokens": 5, "output_tokens": 1},
    ]
    assert sum_usage(records) == {"input_tokens": 15, "output_tokens": 5}


def test_sum_usage_empty_is_unavailable() -> None:
    assert sum_usage([]) == {"input_tokens": None, "output_tokens": None}


def test_callback_lifecycle_closes_each_logical_call_with_stable_indexes(tmp_path) -> None:
    journal = CallJournal(tmp_path)
    records = start_usage_collection(journal, provider_host="provider.invalid")
    handler = current_usage_handler()

    handler.on_llm_start({"name": "fake"}, ["FAKE_PROMPT_MUST_NOT_PERSIST"], run_id="call-a")
    handler.on_llm_end(FakeResponse({"prompt_tokens": 10, "completion_tokens": 4}), run_id="call-a")
    handler.on_llm_start({"name": "fake"}, ["SECOND_FAKE_PROMPT"], run_id="call-b")
    handler.on_llm_end(FakeResponse({"prompt_tokens": 5, "completion_tokens": 1}), run_id="call-b")

    summary = journal.summarize()
    assert summary.coverage == "full"
    assert summary.model_call_count == 2
    assert summary.transport_attempt_count == 2
    assert summary.input_tokens == 15
    assert summary.output_tokens == 5
    assert records == [
        {"input_tokens": 10, "output_tokens": 4},
        {"input_tokens": 5, "output_tokens": 1},
    ]
    assert sorted(path.name for path in (tmp_path / "usage-calls").glob("*.json")) == ["000001.json", "000002.json"]
    persisted = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "FAKE_PROMPT" not in persisted


def test_callback_504_closes_call_as_provider_error_before_first_response(tmp_path) -> None:
    class Provider504(RuntimeError):
        status_code = 504

    journal = CallJournal(tmp_path)
    start_usage_collection(journal, provider_host="provider.invalid")
    handler = current_usage_handler()
    handler.on_llm_start({}, ["FAKE_PROMPT"], run_id="call-504")

    handler.on_llm_error(Provider504("FAKE_RESPONSE_MUST_NOT_PERSIST"), run_id="call-504")

    summary = journal.summarize()
    assert summary.coverage == "unavailable"
    assert summary.unavailable_reason == "provider_error_before_usage"
    assert summary.error_call_count == 1
    assert summary.transport_attempt_count == 1
    assert summary.input_tokens is None
    persisted = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "FAKE_RESPONSE" not in persisted


def test_callback_success_without_usage_is_a_provider_usage_missing_gate_failure(tmp_path) -> None:
    journal = CallJournal(tmp_path)
    start_usage_collection(journal, provider_host="provider.invalid")
    handler = current_usage_handler()
    handler.on_llm_start({}, ["prompt"], run_id="missing-usage")

    handler.on_llm_end(FakeResponse(None), run_id="missing-usage")

    summary = journal.summarize()
    assert summary.coverage == "unavailable"
    assert summary.unavailable_reason == "provider_usage_missing"
    assert summary.completed_call_count == 1
