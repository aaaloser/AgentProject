"""Accepted CodeAgent handoff bodies live in one private in-memory slot."""
from dataclasses import asdict, dataclass

from mokioclaw.core.task_observation import OPAQUE_ID

SCORE_KEYS = ("modification", "self_test", "formal_boundary", "remaining_information", "downstream")
SCORE_VALUES = frozenset({"pass", "fail", "unreviewed", "not_applicable"})


@dataclass(frozen=True)
class HandoffIdentity:
    task_id: str
    attempt_id: int
    ordinal: int


@dataclass(frozen=True)
class HandoffView:
    identity: HandoffIdentity
    summary: str | None
    inspectable: bool


@dataclass(frozen=True)
class HandoffScores:
    modification: str = "unreviewed"
    self_test: str = "unreviewed"
    formal_boundary: str = "unreviewed"
    remaining_information: str = "unreviewed"
    downstream: str = "unreviewed"


def valid_scores(scores):
    return (type(scores) is HandoffScores and
            all(type(v) is str and v in SCORE_VALUES for v in asdict(scores).values()))


class HandoffMemory:
    def __init__(self, task_id: str):
        if type(task_id) is not str or OPAQUE_ID.fullmatch(task_id) is None:
            raise ValueError("calibration_observation_invalid")
        self.task_id = task_id
        self._current = None
        self._indexes = []
        self.valid = True

    @property
    def indexes(self):
        # Fresh numeric-only copies; callers cannot mutate authoritative indexes.
        return [{**row, "identity": dict(row["identity"]), "scores": dict(row["scores"])}
                for row in self._indexes]

    def accept(self, attempt_id: int, summary: str) -> HandoffIdentity | None:
        if (not self.valid or type(attempt_id) is not int or not 1 <= attempt_id <= 3
                or type(summary) is not str or len(self._indexes) >= 24):
            self.valid = False
            self.clear()
            return None
        try:
            size = len(summary.encode("utf-8"))
        except UnicodeError:
            self.valid = False
            self.clear()
            return None
        return self._accept(attempt_id, summary, size)

    def accept_oversize(self, attempt_id: int, size: int) -> HandoffIdentity | None:
        if (not self.valid or type(attempt_id) is not int or not 1 <= attempt_id <= 3
                or type(size) is not int or size <= 65536 or len(self._indexes) >= 24):
            self.valid = False
            self.clear()
            return None
        return self._accept(attempt_id, None, size)

    def _accept(self, attempt_id, summary, size):
        self.clear()
        identity = HandoffIdentity(self.task_id, attempt_id, len(self._indexes) + 1)
        inspectable = size <= 65536
        self._current = HandoffView(identity, summary if inspectable else None, inspectable)
        self._indexes.append({"identity": asdict(identity), "bytes": size,
                              "status": "pending" if inspectable else "oversize",
                              "scores": asdict(HandoffScores())})
        return identity

    def view(self, identity: HandoffIdentity) -> HandoffView | None:
        return self._current if self.valid and self._current is not None and self._current.identity == identity else None

    def score(self, identity: HandoffIdentity, scores: HandoffScores) -> bool:
        current = self.view(identity)
        if current is None or not current.inspectable or not valid_scores(scores):
            return False
        row = self._indexes[-1]
        row["scores"] = asdict(scores)
        row["status"] = "unreviewed" if "unreviewed" in row["scores"].values() else "reviewed"
        return True

    def clear(self) -> None:
        if self._indexes and self._indexes[-1]["status"] == "pending":
            self._indexes[-1]["status"] = "unreviewed"
        self._current = None
