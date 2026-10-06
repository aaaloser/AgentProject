from __future__ import annotations

import re
import socket
import time
import webbrowser
from pathlib import Path
from threading import Thread
from typing import Sequence

import uvicorn

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec
from mokioclaw.dashboard.task_service import FakeTaskRunner, TaskService
from mokioclaw.providers.openai_provider import ProviderSettings


def launch_dashboard(
    paths: Sequence[Path], *, open_browser: bool = True, task_root: Path | None = None,
    task_image: str | None = None, enable_agent: bool = False,
    calibration_root: Path | None = None,
    calibration_continue_task: str | None = None,
    calibration_expected_spec_sha256: str | None = None,
    calibration_expected_source_root: Path | None = None,
) -> None:
    """Serve explicitly registered local repositories and optional task capability."""
    from mokioclaw.dashboard.task_observation_continuation import parse_continuation_options
    continuation = parse_continuation_options(
        task_id=calibration_continue_task, expected_spec_sha256=calibration_expected_spec_sha256,
        expected_source_root=calibration_expected_source_root, calibration_root=calibration_root,
        task_root=task_root, enable_agent=enable_agent, task_image=task_image, repo_paths=paths,
    )
    if calibration_root is not None:
        from mokioclaw.dashboard.task_diagnostic_viewer import validate_calibration
        validate_calibration(calibration_root, task_root, enable_agent=enable_agent)
    if enable_agent and (task_root is None or task_image is None
                         or re.fullmatch(r"sha256:[0-9a-f]{64}", task_image) is None):
        raise ValueError("Agent mode needs a task root and fixed local image digest")
    if task_image is not None and not enable_agent:
        raise ValueError("Task image requires Agent mode")
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths(paths, reader)
    task_service = TaskService(
        catalog, reader, task_root, fake_runner=None if enable_agent else FakeTaskRunner(),
        **({"continuation_options": continuation, "calibration_root": calibration_root} if continuation is not None else {}),
    ) if task_root is not None else None
    try:
        if calibration_root is not None:
            from mokioclaw.dashboard.task_diagnostic_viewer import launch_viewer
            assert task_service is not None
            manager = task_service.configure_calibration(calibration_root)
            manager.start_servers()
            manager._viewer_launch = launch_viewer(manager.viewer_bootstrap)
            deadline = time.monotonic() + 3
            while not manager.viewer_ready:
                if (not manager.valid or manager._viewer_launch.process.poll() is not None
                        or time.monotonic() >= deadline):
                    raise ValueError("calibration_observation_invalid")
                time.sleep(0.01)
        if enable_agent:
            assert task_service is not None and task_image is not None
            task_service.configure_agent(ProviderSettings.from_environment(), task_image)
        if continuation is not None:
            catalog = task_service.catalog
        app = create_dashboard_app(catalog, reader, CursorCodec(), task_service=task_service)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
            server = uvicorn.Server(config)
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, name="mokioclaw-dashboard", daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("The local dashboard could not start.")
                    time.sleep(0.01)
                url = f"http://127.0.0.1:{port}/"
                print(f"Dashboard: {url}")
                if open_browser:
                    webbrowser.open(url)
                thread.join()
            except KeyboardInterrupt:
                pass
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("The local dashboard did not stop cleanly.")
    finally:
        if task_service is not None:
            task_service.close()
