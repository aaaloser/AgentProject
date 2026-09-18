import pytest

from config_cli.cli import main


def test_show_defaults_to_compatible_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("CONFIG_CLI_HOST", raising=False)
    monkeypatch.delenv("CONFIG_CLI_RETRIES", raising=False)

    assert main(["show"]) == 0

    assert capsys.readouterr().out.splitlines() == ["host=localhost", "retries=3"]


def test_show_accepts_cli_values(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("CONFIG_CLI_HOST", raising=False)
    monkeypatch.delenv("CONFIG_CLI_RETRIES", raising=False)

    assert main(["show", "--host", "cli-host", "--retries", "9"]) == 0

    assert capsys.readouterr().out.splitlines() == ["host=cli-host", "retries=9"]
