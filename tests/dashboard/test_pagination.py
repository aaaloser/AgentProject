from __future__ import annotations

import pytest

from mokioclaw.dashboard.pagination import CursorCodec, InvalidCursor


SHA = "a" * 40


def test_cursor_round_trip_binds_repo_anchor_and_offset() -> None:
    codec = CursorCodec()
    token = codec.encode("repo_12345678", SHA, 50)
    cursor = codec.decode(token, "repo_12345678")
    assert (cursor.repo_id, cursor.anchor_sha, cursor.offset) == ("repo_12345678", SHA, 50)
    assert len(token) <= 512
    assert ":\\" not in token and "/" not in token


def test_cursor_rejects_tampering_cross_repo_and_other_process() -> None:
    codec = CursorCodec()
    token = codec.encode("repo_12345678", SHA, 100)
    with pytest.raises(InvalidCursor):
        codec.decode(token, "repo_87654321")
    with pytest.raises(InvalidCursor):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"), "repo_12345678")
    with pytest.raises(InvalidCursor):
        CursorCodec().decode(token, "repo_12345678")


@pytest.mark.parametrize(
    ("repo_id", "sha", "offset"),
    [("repo_12345678", SHA, -1), ("repo_12345678", "HEAD", 0), ("../repo", SHA, 0)],
)
def test_cursor_rejects_invalid_inputs(repo_id: str, sha: str, offset: int) -> None:
    with pytest.raises(InvalidCursor):
        CursorCodec().encode(repo_id, sha, offset)


def test_cursor_rejects_overlong_and_malformed_tokens() -> None:
    codec = CursorCodec()
    for token in ("A" * 513, "not-a-token", "a.b.c", "!@#$", "!.b"):
        with pytest.raises(InvalidCursor):
            codec.decode(token, "repo_12345678")
