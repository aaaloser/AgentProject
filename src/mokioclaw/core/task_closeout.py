"""Task-local numeric closeout policy; no provider or execution dependencies."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Literal


class CloseoutPurpose(Enum):
    REPAIR = "repair"
    HANDOFF = "handoff"
    PLANNER = "planner"
    PRE_COMPRESS = "pre_compress"
    VERIFIER = "verifier"
    POST_COMPRESS = "post_compress"


class CloseoutMode(Enum):
    INACTIVE = "inactive"
    REPAIR = "repair"
    CLOSING = "closing"
    FINISHED = "finished"
    FAILED = "failed"


class TaskCloseoutError(RuntimeError):
    def __init__(self, reason: Literal["budget_slots_insufficient", "phase_limit", "invalid_handoff"]):
        if reason not in {"budget_slots_insufficient", "phase_limit", "invalid_handoff"}:
            raise ValueError("task_closeout_reason_invalid")
        self.reason = reason
        super().__init__("task_closeout_incomplete")


_SLOTS = {
    CloseoutPurpose.HANDOFF: 1, CloseoutPurpose.PLANNER: 2,
    CloseoutPurpose.PRE_COMPRESS: 1, CloseoutPurpose.VERIFIER: 2,
    CloseoutPurpose.POST_COMPRESS: 1,
}


def _nonnegative(value):
    if type(value) is not int or value < 0:
        raise ValueError("task_closeout_number_invalid")
    return value


@dataclass(frozen=True)
class CloseoutSnapshot:
    mode: str
    E_repair: int
    R_calls: int
    R_tokens: int
    iterations_left: int | None
    slots: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class CloseoutNotice:
    kind: str
    purpose: str | None
    call_no: int | None
    calls_left: int | None
    tokens_left: int | None
    reasons: tuple[str, ...]
    snapshot: CloseoutSnapshot
    gate: str | None = None


class TaskCloseout:
    def __init__(self, output_limit: int, *, observer: Callable[[CloseoutNotice], None] | None = None):
        if _nonnegative(output_limit) == 0:
            raise ValueError("task_closeout_number_invalid")
        self._output_limit = output_limit
        self._mode = CloseoutMode.INACTIVE
        self._attempt = 0
        self._remaining = {}
        self._maxima = {}
        self._global_max = 0
        self._repair_started = False
        self._delegation_admitted = False
        self._adopted = set()
        self._monitor_origin = None
        self._observer = observer

    def snapshot(self, *, iterations_left: int | None = None) -> CloseoutSnapshot:
        return CloseoutSnapshot(
            self._mode.value, self.estimate(CloseoutPurpose.REPAIR),
            self.remaining_calls, self.remaining_tokens, iterations_left,
            tuple((p.value, self._remaining.get(p, 0)) for p in _SLOTS),
        )

    def _notice(self, kind="policy_decision", *, purpose=None, call_no=None,
                calls_left=None, tokens_left=None, iterations_left=None, reasons=(), gate=None):
        if self._observer is not None:
            try:
                self._observer(CloseoutNotice(
                    kind, purpose.value if purpose is not None else None, call_no,
                    calls_left, tokens_left, reasons, self.snapshot(iterations_left=iterations_left), gate,
                ))
            except Exception:
                # The adapter owns invalidation; observation cannot change policy.
                pass

    @property
    def mode(self):
        return self._mode

    @property
    def remaining_calls(self):
        return sum(self._remaining.values())

    @property
    def remaining_tokens(self):
        return sum(n * self.estimate(p) for p, n in self._remaining.items())

    @property
    def delegation_admitted(self):
        return self._delegation_admitted

    @property
    def monitor_origin(self):
        return self._monitor_origin

    def begin_attempt(self, attempt_id: int) -> None:
        _nonnegative(attempt_id)
        if attempt_id == self._attempt and attempt_id > 0:
            return
        if attempt_id != self._attempt + 1:
            raise ValueError("task_closeout_attempt_invalid")
        self._attempt = attempt_id
        self._mode = CloseoutMode.REPAIR
        self._remaining = dict(_SLOTS)
        self._delegation_admitted = False
        self._monitor_origin = None

    def estimate(self, purpose: CloseoutPurpose) -> int:
        if not isinstance(purpose, CloseoutPurpose):
            raise ValueError("task_closeout_purpose_invalid")
        maximum = self._maxima.get(purpose, self._global_max)
        return (5 * max(self._output_limit, maximum) + 3) // 4

    def record_usage(self, purpose: CloseoutPurpose | None, total: int) -> None:
        _nonnegative(total)
        if purpose is not None and not isinstance(purpose, CloseoutPurpose):
            raise ValueError("task_closeout_purpose_invalid")
        self._global_max = max(self._global_max, total)
        if purpose is not None:
            self._maxima[purpose] = max(self._maxima.get(purpose, 0), total)

    def _prospective_tokens(self):
        return sum(n * self.estimate(p) for p, n in _SLOTS.items())

    def admit_delegation(self, *, calls_left: int, tokens_left: int) -> bool:
        reasons = tuple(r for r, triggered in (
            ("calls", calls_left < 8),
            ("tokens", self._repair_started and tokens_left <=
             self.estimate(CloseoutPurpose.REPAIR) + self._prospective_tokens()),
        ) if triggered) if self._mode == CloseoutMode.REPAIR else ()
        self._notice(calls_left=calls_left, tokens_left=tokens_left, reasons=reasons, gate="delegation")
        if self._mode != CloseoutMode.REPAIR:
            return False
        if self._delegation_admitted:
            return True
        if calls_left < 8 or (self._repair_started and
                tokens_left <= self.estimate(CloseoutPurpose.REPAIR) + self._prospective_tokens()):
            self.enter_closing()
            self._notice(calls_left=calls_left, tokens_left=tokens_left, reasons=reasons, gate="delegation")
            return False
        self._remaining = dict(_SLOTS)
        self._delegation_admitted = True
        self._notice(calls_left=calls_left, tokens_left=tokens_left, gate="delegation")
        return True

    def decide_repair(self, *, calls_left: int, tokens_left: int, iterations_left: int) -> CloseoutMode:
        reasons = tuple(r for r, triggered in (
            ("calls", calls_left <= self.remaining_calls),
            ("tokens", self._repair_started and tokens_left <=
             self.estimate(CloseoutPurpose.REPAIR) + self.remaining_tokens),
            ("iterations", iterations_left <= 1),
        ) if triggered) if self._mode == CloseoutMode.REPAIR else ()
        self._notice(calls_left=calls_left, tokens_left=tokens_left,
                     iterations_left=iterations_left, reasons=reasons)
        if self._mode == CloseoutMode.REPAIR and (
                iterations_left <= 1 or calls_left <= self.remaining_calls or
                (self._repair_started and tokens_left <=
                 self.estimate(CloseoutPurpose.REPAIR) + self.remaining_tokens)):
            self.enter_closing()
            self._notice(calls_left=calls_left, tokens_left=tokens_left,
                         iterations_left=iterations_left, reasons=reasons)
        return self._mode

    def enter_closing(self) -> None:
        if self._mode == CloseoutMode.REPAIR:
            self._mode = CloseoutMode.CLOSING

    def claim_invoke(self, purpose: CloseoutPurpose) -> None:
        if not isinstance(purpose, CloseoutPurpose):
            raise ValueError("task_closeout_purpose_invalid")
        self._notice(purpose=purpose, gate="phase")
        if self._mode in {CloseoutMode.FINISHED, CloseoutMode.FAILED}:
            raise TaskCloseoutError("phase_limit")
        if purpose == CloseoutPurpose.REPAIR:
            if self._mode != CloseoutMode.REPAIR:
                raise TaskCloseoutError("phase_limit")
            self._repair_started = True
        else:
            if self._remaining.get(purpose, 0) <= 0:
                raise TaskCloseoutError("phase_limit")
            self._remaining[purpose] -= 1

    def complete_phase(self, purpose: CloseoutPurpose) -> None:
        if purpose not in _SLOTS:
            raise ValueError("task_closeout_purpose_invalid")
        changed = self._remaining.get(purpose, 0) > 0
        self._remaining[purpose] = 0
        if purpose == CloseoutPurpose.HANDOFF:
            self._delegation_admitted = False
        if changed:
            self._notice("phase_released", purpose=purpose)

    def adopt_planner_response(self, call_no: int, total: int) -> None:
        if type(call_no) is not int or not 1 <= call_no <= 24:
            raise ValueError("task_closeout_call_invalid")
        _nonnegative(total)
        if call_no in self._adopted:
            return
        self.claim_invoke(CloseoutPurpose.PLANNER)
        self._adopted.add(call_no)
        self.record_usage(CloseoutPurpose.PLANNER, total)
        self._notice("adopt_existing_call", purpose=CloseoutPurpose.PLANNER, call_no=call_no)

    def admit_next_attempt(self, *, calls_left: int, tokens_left: int) -> bool:
        self._notice(calls_left=calls_left, tokens_left=tokens_left, gate="attempt",
                     reasons=tuple(r for r, yes in (
                         ("calls", calls_left < 9),
                         ("tokens", tokens_left <= self._prospective_tokens() +
                          self.estimate(CloseoutPurpose.PLANNER) + self.estimate(CloseoutPurpose.REPAIR)),
                     ) if yes))
        return calls_left >= 9 and tokens_left > (
            self._prospective_tokens() + self.estimate(CloseoutPurpose.PLANNER) +
            self.estimate(CloseoutPurpose.REPAIR))

    def note_node_return(self, node: Literal["planner", "verifier"]) -> None:
        if node not in {"planner", "verifier"}:
            raise ValueError("task_closeout_origin_invalid")
        self._monitor_origin = node

    def finish(self, *, failed: bool) -> None:
        self._mode = CloseoutMode.FAILED if failed else CloseoutMode.FINISHED
