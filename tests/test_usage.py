from mokioclaw.providers.usage import (
    start_usage_collection,
    sum_usage,
    current_usage_handler,
)


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
