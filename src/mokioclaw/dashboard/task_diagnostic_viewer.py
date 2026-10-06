"""Explicit native private viewer; imports no provider or task execution capability."""
from dataclasses import asdict, dataclass
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from mokioclaw.dashboard.task_diagnostic_ipc import (
    DiagnosticBootstrap, ERROR, MAX_FRAME, bootstrap_from_wire, bootstrap_to_wire,
    connect_pipe, decode_frame, encode_frame,
)
from mokioclaw.dashboard.task_handoff_observation import (
    HandoffIdentity, HandoffScores, HandoffView, SCORE_KEYS, SCORE_VALUES, valid_scores,
)


def filtered_viewer_environment(source=None):
    source = os.environ if source is None else source
    allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG")
    return {**{k: source[k] for k in allowed if k in source},
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONDONTWRITEBYTECODE": "1"}


def validate_calibration(root, task_root, *, enable_agent, platform=None, tkinter_available=None):
    from mokioclaw.dashboard.task_diagnostics import _safe_path
    try:
        platform = os.name if platform is None else platform
        if tkinter_available is None:
            tkinter_available = importlib.util.find_spec("tkinter") is not None
        root = _safe_path(root)
        if (not enable_agent or task_root is None or platform != "nt" or not tkinter_available
                or _safe_path(task_root).resolve() != (root / "tasks").resolve()):
            raise ValueError
    except Exception:
        raise ValueError("calibration_config_invalid") from None


@dataclass
class ViewerLaunch:
    process: object

    def close(self):
        # Popen owns the original child process handle; no PID-only lookup/kill.
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=3)
        except Exception:
            pass


def launch_viewer(bootstrap: DiagnosticBootstrap, *, spawn=None, environment=None):
    if bootstrap.role != "viewer":
        raise ValueError(ERROR)
    spawn = subprocess.Popen if spawn is None else spawn
    launch = None
    try:
        wire = bootstrap_to_wire(bootstrap)
        process = spawn(
            [sys.executable, "-P", "-B", "-m", "mokioclaw.dashboard.task_diagnostic_viewer"],
            cwd=Path(__file__).resolve().parents[3], env=filtered_viewer_environment(environment),
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        launch = ViewerLaunch(process)
        process.stdin.write(json.dumps(wire, separators=(",", ":")).encode("utf-8") + b"\n")
        process.stdin.close()
        return launch
    except Exception:
        if launch is not None:
            launch.close()
        raise ValueError(ERROR) from None


class ViewerController:
    def __init__(self, *, request, render_text):
        self._request, self._render_text = request, render_text
        self._view = None
        self.bound_task = None
        self.valid = True
        self.notice = "absent"

    def bind(self, task_id):
        try:
            reply = self._request("bind", task_id=task_id)
            self.valid = reply["valid"]
            if reply["accepted"]:
                self.bound_task = reply["bound_task"]
                self.render(None)
                return True
        except Exception:
            self.valid = False
            self.render(None)
        return False

    def render(self, view: HandoffView | None):
        self.notice = ("oversize" if type(view) is HandoffView and not view.inspectable
                       and view.identity.task_id == self.bound_task else
                       "available" if type(view) is HandoffView and view.inspectable else "absent")
        if (view is not None and (type(view) is not HandoffView or view.identity.task_id != self.bound_task
                                 or not view.inspectable or type(view.summary) is not str)):
            view = None
        self._view = view
        self._render_text(view.summary if view is not None else "")

    def submit_scores(self, scores):
        if self._view is None or not self.valid or not valid_scores(scores):
            return False
        try:
            reply = self._request("score", identity=asdict(self._view.identity), scores=asdict(scores))
            self.valid = reply["valid"]
            return reply["accepted"] is True
        except Exception:
            self.valid = False
            self.render(None)
            return False

    def poll(self):
        try:
            reply = self._request("poll")
            self.valid = reply["valid"]
            self.bound_task = reply["bound_task"]
            raw = reply["view"] if self.valid else None
            self.render(HandoffView(HandoffIdentity(**raw["identity"]), raw["summary"], raw["inspectable"])
                        if raw is not None else None)
        except Exception:
            self.valid = False
            self.render(None)

    def close(self):
        self.render(None)
        self.valid = False
        try:
            self._request("close")
        except Exception:
            pass


class ViewerChannel:
    def __init__(self, bootstrap, *, connect=connect_pipe):
        bootstrap.validate()
        if bootstrap.role != "viewer":
            raise ValueError(ERROR)
        self.connection = connect(bootstrap)
        self.sequence = 0
        self._failed = False
        self.request("hello")

    def request(self, kind, **values):
        if self._failed:
            raise ValueError(ERROR)
        try:
            self.sequence += 1
            self.connection.send_bytes(encode_frame({"schema_version": 1, "kind": kind,
                                                    "sequence": self.sequence, **values}, role="viewer"))
            if not self.connection.poll(3 if kind == "hello" else 1):
                raise ValueError(ERROR)
            reply = decode_frame(self.connection.recv_bytes(MAX_FRAME), role="viewer")
            if reply["kind"] != "state" or reply["sequence"] != self.sequence:
                raise ValueError(ERROR)
            return reply
        except Exception:
            # Even a pre-send encoding failure must revoke the parent's readiness.
            self._failed = True
            try:
                self.connection.close()
            except Exception:
                pass
            raise ValueError(ERROR) from None


def main(*, bootstrap=None, tk_module=None, channel_factory=ViewerChannel):
    # Tk is loaded/constructed only by this explicit child entry point.
    if bootstrap is None:
        line = sys.stdin.buffer.readline(4096)
        bootstrap = bootstrap_from_wire(json.loads(line))
    if tk_module is None:
        import tkinter as tk_module
    tk = tk_module
    root = tk.Tk()
    root.title("MokioClaw 私有校准观测")
    channel = None
    try:
        channel = channel_factory(bootstrap)
        status = tk.StringVar(value="先绑定一个 prepared Task；此窗口不能运行或审批任务。")
        task = tk.StringVar()
        tk.Entry(root, textvariable=task, width=48).pack()
        tk.Label(root, textvariable=status).pack()
        text = tk.Text(root, width=100, height=30, wrap="word", state="disabled")
        text.pack()
        def render(body):
            # Expose control characters visibly; no URL interpretation or execution.
            display = "".join(f"\\u{ord(c):04x}" if ord(c) < 32 and c not in "\n\t" else c for c in body)
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", display)
            text.configure(state="disabled")
        controller = ViewerController(request=channel.request, render_text=render)
        def bind():
            status.set("已绑定" if controller.bind(task.get()) else "绑定失败")
        tk.Button(root, text="绑定观测", command=bind).pack()
        variables = {name: tk.StringVar(value="unreviewed") for name in SCORE_KEYS}
        for name, variable in variables.items():
            tk.Label(root, text=name).pack()
            tk.OptionMenu(root, variable, *sorted(SCORE_VALUES)).pack()
        def score():
            accepted = controller.submit_scores(HandoffScores(**{k: v.get() for k, v in variables.items()}))
            status.set("评分已接受" if accepted else "评分未接受／交接已更换")
        tk.Button(root, text="提交五维评分", command=score).pack()
        def close():
            controller.close()
            root.destroy()
        tk.Button(root, text="关闭", command=close).pack()
        root.protocol("WM_DELETE_WINDOW", close)
        last_identity = [None]
        def poll():
            controller.poll()
            identity = controller._view.identity if controller._view is not None else None
            if identity != last_identity[0]:
                for variable in variables.values():
                    variable.set("unreviewed")
                last_identity[0] = identity
            if not controller.valid:
                status.set(ERROR + "；请在原工作台处理任务。")
            elif controller.notice == "oversize":
                status.set("交接超过64KiB，不可完整检查；正文未保留，不能评分为通过。")
            elif controller.bound_task is not None:
                status.set("已绑定；当前没有可完整查看的交接。" if controller.notice == "absent" else "已绑定；请核对实际交接后评分。")
            root.after(500, poll)
        root.after(500, poll)
        root.mainloop()
        controller.render(None)
    finally:
        if channel is not None:
            channel.connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Child has DEVNULL streams. No raw exceptions/body/auth output.
        sys.exit(2)
