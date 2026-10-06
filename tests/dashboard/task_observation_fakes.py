"""Synthetic observation helpers; external entry points fail with sticky evidence."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import multiprocessing.connection

from task_closeout_fakes import offline_closeout_guard


TASK_ID = "synthetic_task_0001"
INSTANCE_ID = "synthetic_instance_001"


@contextmanager
def offline_observation_guard(monkeypatch):
    hits = []

    def forbidden(*args, **kwargs):
        hits.append("forbidden")
        raise AssertionError("offline_boundary_touched")

    with offline_closeout_guard(monkeypatch), monkeypatch.context() as patch:
        patch.setattr(multiprocessing.connection, "Listener", forbidden)
        patch.setattr(multiprocessing.connection, "Client", forbidden)
        from mokioclaw.providers.openai_provider import ProviderSettings
        patch.setattr(ProviderSettings, "from_environment", forbidden)
        import tkinter
        patch.setattr(tkinter, "Tk", forbidden)
        try:
            yield hits
        finally:
            assert not hits, "offline_boundary_touched"


@dataclass
class MemorySink:
    records: list = field(default_factory=list)

    def emit(self, record):
        self.records.append(record)
        return True


def utc_clock():
    return datetime(2026, 10, 4, tzinfo=timezone.utc)
