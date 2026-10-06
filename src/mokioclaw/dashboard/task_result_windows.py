"""In-memory, executed-result continuations; no files, models or commands."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import secrets
from typing import Any


class ResultWindowError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ResultWindowError("unsupported_content") from None


@dataclass(frozen=True)
class ResultSegment:
    kind: str
    value: str | tuple[dict, ...]


@dataclass(frozen=True)
class Reservation:
    key: str


@dataclass(frozen=True)
class ResultRef:
    key: str


@dataclass(frozen=True)
class _Payload:
    encoded: bytes
    committed: bool
    preserve: bool


class ResultWindowStore:
    def __init__(self, identity: tuple[str, int, str], *, max_bytes: int, max_results: int,
                 max_cursors: int = 1024) -> None:
        if min(max_bytes, max_results, max_cursors) < 1:
            raise ResultWindowError("result_capacity")
        self.identity = identity
        self.max_bytes, self.max_results, self.max_cursors = max_bytes, max_results, max_cursors
        self._payloads: OrderedDict[str, _Payload] = OrderedDict()
        self._cursors: OrderedDict[str, tuple[str, str, int]] = OrderedDict()

    @property
    def payload_bytes(self) -> int:
        return sum(len(payload.encoded) for payload in self._payloads.values())

    @property
    def cursor_count(self) -> int:
        return len(self._cursors)

    def _drop(self, key: str) -> None:
        self._payloads.pop(key, None)
        for cursor, location in list(self._cursors.items()):
            if location[0] == key:
                del self._cursors[cursor]

    def reserve(self, result: dict, segments: dict[str, ResultSegment], *,
                preserve_failure: bool = False) -> Reservation:
        if not isinstance(result, dict) or not segments:
            raise ResultWindowError("unsupported_content")
        base = dict(result)
        saved = {}
        for name, segment in segments.items():
            if not isinstance(name, str) or name not in base:
                raise ResultWindowError("unsupported_content")
            if segment.kind == "text":
                valid = isinstance(segment.value, str)
            elif segment.kind == "records":
                valid = isinstance(segment.value, tuple) and all(isinstance(item, dict) for item in segment.value)
            else:
                valid = False
            if not valid or _json(base.pop(name)) != _json(segment.value):
                raise ResultWindowError("unsupported_content")
            saved[name] = {"kind": segment.kind, "value": segment.value}
        encoded = _json({"base": base, "segments": saved})
        if len(encoded) > self.max_bytes:
            raise ResultWindowError("result_capacity")
        while len(self._payloads) >= self.max_results or self.payload_bytes + len(encoded) > self.max_bytes:
            candidate = next((key for key, payload in self._payloads.items()
                              if payload.committed and not payload.preserve), None)
            if candidate is None:
                raise ResultWindowError("result_capacity")
            self._drop(candidate)
        key = secrets.token_urlsafe(24)
        self._payloads[key] = _Payload(encoded, False, preserve_failure)
        return Reservation(key)

    def commit(self, reservation: Reservation, *, executed: bool) -> ResultRef:
        payload = self._payloads.get(reservation.key) if type(reservation) is Reservation else None
        if payload is None or payload.committed or not executed:
            if payload is not None and not executed:
                self.abort(reservation)
            raise ResultWindowError("result_unavailable")
        if payload.preserve:
            for key, previous in list(self._payloads.items()):
                if previous.committed and previous.preserve:
                    self._payloads[key] = _Payload(previous.encoded, True, False)
        self._payloads[reservation.key] = _Payload(payload.encoded, True, payload.preserve)
        return ResultRef(reservation.key)

    def abort(self, reservation: Reservation) -> None:
        if type(reservation) is Reservation:
            payload = self._payloads.get(reservation.key)
            if payload is not None and not payload.committed:
                self._drop(reservation.key)

    def _load(self, key: str) -> dict:
        payload = self._payloads.get(key)
        if payload is None or not payload.committed:
            raise ResultWindowError("result_unavailable")
        return json.loads(payload.encoded)

    def _cursor(self, key: str, name: str, start: int) -> str:
        location = (key, name, start)
        for cursor, existing in self._cursors.items():
            if existing == location:
                return cursor
        cursor = secrets.token_urlsafe(24)
        self._cursors[cursor] = location
        while len(self._cursors) > self.max_cursors:
            self._cursors.popitem(last=False)
        return cursor

    @staticmethod
    def _fit(value: str | list, start: int, limit: int, kind: str, make_page, budget: int,
             body_budget: int = 8192):
        # Search on actual canonical JSON and body bytes, not character estimates.
        low, high, selected = 0, min(len(value) - start, limit), None
        while low <= high:
            count = (low + high) // 2
            fragment = value[start:start + count]
            body = fragment.encode("utf-8") if kind == "text" else _json(fragment)
            candidate = make_page(fragment, start + count)
            if len(body) <= body_budget and len(_json(candidate)) <= min(16384, budget):
                selected = (candidate, start + count)
                low = count + 1
            else:
                high = count - 1
        if selected is None or (selected[1] == start and start < len(value)):
            raise ResultWindowError("input_too_large")
        return selected

    def first_page(self, ref: ResultRef, *, json_budget: int) -> dict:
        if type(ref) is not ResultRef:
            raise ResultWindowError("result_unavailable")
        saved = self._load(ref.key)
        return self._first_page(saved, ref.key, json_budget=json_budget, issue=True)

    def preview(self, reservation: Reservation, *, json_budget: int) -> None:
        payload = self._payloads.get(reservation.key)
        if payload is None or payload.committed:
            raise ResultWindowError("result_unavailable")
        self._first_page(json.loads(payload.encoded), reservation.key, json_budget=json_budget, issue=False)

    def cursor_kind(self, cursor: str) -> str | None:
        location = self._cursors.get(cursor) if isinstance(cursor, str) else None
        if location is None:
            return None
        return self._load(location[0])["segments"][location[1]]["kind"]

    def _first_page(self, saved: dict, key: str, *, json_budget: int, issue: bool) -> dict:
        page = dict(saved["base"])
        page["result_windows"] = {}
        page["complete"] = False
        # Seed minimum progress for every segment so earlier fills cannot spend
        # the canonical JSON space required by later segments (including escapes).
        for name, segment in saved["segments"].items():
            page[name] = segment["value"][:1]
            end = len(page[name])
            page["result_windows"][name] = {
                "kind": segment["kind"], "original_length": len(segment["value"]), "start": 0, "end": end,
                "content_truncated": end < len(segment["value"]),
                "next_result_read": {"cursor": "x" * 32, "limit": 8192} if end < len(segment["value"]) else None,
            }
        used_body = 0
        ordered_segments = list(saved["segments"].items())
        for index, (name, segment) in enumerate(ordered_segments):
            value = segment["value"]
            minimum_later = sum(len(later["value"][:1].encode("utf-8")) if later["kind"] == "text"
                                else len(_json(later["value"][:1]))
                                for _, later in ordered_segments[index + 1:])
            available_body = 8192 - used_body - minimum_later

            def candidate(fragment, end):
                result = {**page, name: fragment, "result_windows": {**page["result_windows"]}}
                result["result_windows"][name] = {
                    "kind": segment["kind"], "original_length": len(value), "start": 0, "end": end,
                    "content_truncated": end < len(value),
                    "next_result_read": {"cursor": "x" * 32, "limit": 8192} if end < len(value) else None,
                }
                return result

            page, end = self._fit(value, 0, len(value), segment["kind"], candidate, json_budget, available_body)
            used_body += len(page[name].encode("utf-8")) if segment["kind"] == "text" else len(_json(page[name]))
            if end < len(value) and issue:
                page["result_windows"][name]["next_result_read"]["cursor"] = self._cursor(key, name, end)
        page["complete"] = all(not window["content_truncated"] for window in page["result_windows"].values()) and saved["base"].get("upstream_complete", True)
        if len(_json(page)) > min(16384, json_budget):
            raise ResultWindowError("input_too_large")
        return page

    def read(self, cursor: str, limit: int, *, identity: tuple[str, int, str], json_budget: int) -> dict:
        if identity != self.identity or not isinstance(cursor, str) or cursor not in self._cursors:
            raise ResultWindowError("result_unavailable")
        key, name, start = self._cursors[cursor]
        saved = self._load(key)
        if type(limit) is not int or limit < 1:
            raise ResultWindowError("task_read_window_invalid")
        segment = saved["segments"][name]
        value = segment["value"]
        upstream_complete = saved["base"].get("upstream_complete", True)

        def candidate(fragment, end):
            return {"ok": True, "kind": segment["kind"], "content" if segment["kind"] == "text" else "records": fragment,
                    "original_length": len(value), "start": start, "end": end,
                    "content_truncated": end < len(value), "complete": end == len(value) and upstream_complete,
                    "upstream_complete": upstream_complete,
                    "next_result_read": {"cursor": "x" * 32, "limit": limit} if end < len(value) else None}

        page, end = self._fit(value, start, limit, segment["kind"], candidate, json_budget)
        if end < len(value):
            page["next_result_read"]["cursor"] = self._cursor(key, name, end)
        return page

    def clear(self) -> None:
        self._payloads.clear()
        self._cursors.clear()
