"""Strictly offline fixtures. No real model, network or command fallback."""

from contextlib import contextmanager
import os
import socket
import subprocess


@contextmanager
def offline_context_guard(monkeypatch, *, on_forbidden=None):
    # Import modules before blocking their constructors, never instantiate them.
    import dotenv
    import dotenv.main
    import langchain_openai
    from mokioclaw.agents import code_agent
    from mokioclaw.core import agent, execution
    from mokioclaw.dashboard import task_executor
    from mokioclaw.graph import nodes
    from mokioclaw.providers import openai_provider

    def forbidden(*args, **kwargs):
        if on_forbidden is not None:
            on_forbidden()
        raise AssertionError("offline_boundary_touched")

    with monkeypatch.context() as patch:
        for owner, name in (
            (agent, "create_task_model"), (code_agent, "create_model"),
            (openai_provider, "create_model"), (openai_provider, "create_task_model"),
            (openai_provider, "ChatOpenAI"), (langchain_openai, "ChatOpenAI"),
            (openai_provider, "load_dotenv"), (dotenv, "load_dotenv"),
            (dotenv.main, "load_dotenv"), (dotenv.main, "dotenv_values"),
            (dotenv, "dotenv_values"), (agent, "load_dotenv"),
            (nodes, "load_dotenv"), (nodes, "create_model"),
            (socket.socket, "connect"), (socket.socket, "connect_ex"),
            (socket, "create_connection"), (task_executor.DockerCLI, "run"),
            (socket.socket, "bind"), (socket.socket, "listen"), (socket.socket, "accept"),
            (task_executor.IsolatedCommandExecutor, "execute"),
            (task_executor.ApprovedExecutor, "execute"),
            (execution.CommandExecutor, "run"),
            (subprocess, "run"), (subprocess, "Popen"), (os, "system"),
        ):
            patch.setattr(owner, name, forbidden)
        import httpx
        import urllib.request
        patch.setattr(httpx.Client, "send", forbidden)
        patch.setattr(httpx.AsyncClient, "send", forbidden)
        patch.setattr(urllib.request, "urlopen", forbidden)
        yield
