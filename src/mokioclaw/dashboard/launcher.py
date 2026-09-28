from __future__ import annotations

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
from mokioclaw.dashboard.task_service import TaskService


def launch_dashboard(
    paths: Sequence[Path], *, open_browser: bool = True, task_root: Path | None = None,
    task_image: str | None = None, enable_agent: bool = False,
) -> None:
    """Serve only explicitly registered local repositories until interrupted."""
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths(paths, reader)
    task_service = TaskService(catalog, reader, task_root) if task_root is not None else None
    try:
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
