from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from secrets import token_bytes


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True)
class PageCursor:
    repo_id: str
    anchor_sha: str
    offset: int


class CursorCodec:
    def __init__(self) -> None:
        self._key = token_bytes(32)

    def encode(self, repo_id: str, anchor_sha: str, offset: int) -> str:
        self._validate(repo_id, anchor_sha, offset)
        payload = json.dumps(
            {"repo_id": repo_id, "anchor_sha": anchor_sha.lower(), "offset": offset},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        token = f"{self._b64(payload)}.{self._b64(signature)}"
        if len(token) > 512:
            raise InvalidCursor("Cursor is too long")
        return token

    def decode(self, token: str, expected_repo_id: str) -> PageCursor:
        if not isinstance(token, str) or len(token) > 512 or token.count(".") != 1:
            raise InvalidCursor("Malformed cursor")
        payload_part, signature_part = token.split(".")
        try:
            payload = self._unb64(payload_part)
            signature = self._unb64(signature_part)
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursor("Cursor signature is invalid")
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {"repo_id", "anchor_sha", "offset"}:
                raise InvalidCursor("Cursor fields are invalid")
            self._validate(value["repo_id"], value["anchor_sha"], value["offset"])
            if value["repo_id"] != expected_repo_id:
                raise InvalidCursor("Cursor belongs to another repository")
            return PageCursor(value["repo_id"], value["anchor_sha"], value["offset"])
        except (UnicodeError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, InvalidCursor):
                raise
            raise InvalidCursor("Malformed cursor") from exc

    @staticmethod
    def _validate(repo_id: str, anchor_sha: str, offset: int) -> None:
        if (
            not isinstance(repo_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", repo_id) is None
            or not isinstance(anchor_sha, str)
            or re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", anchor_sha) is None
            or type(offset) is not int
            or offset < 0
        ):
            raise InvalidCursor("Invalid cursor input")

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @classmethod
    def _unb64(cls, value: str) -> bytes:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if cls._b64(raw) != value:
            raise InvalidCursor("Non-canonical cursor encoding")
        return raw
