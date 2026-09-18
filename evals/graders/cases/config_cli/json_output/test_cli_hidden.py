import json

import pytest

from config_cli.cli import main


def test_json_output_uses_a_stable_schema(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CONFIG_CLI_HOST", raising=False)
    monkeypatch.delenv("CONFIG_CLI_RETRIES", raising=False)
    config = tmp_path / "config.toml"
    config.write_text('host = "file-host"\nretries = 7\n', encoding="utf-8")

    assert main(["show", "--config", str(config), "--format", "json"]) == 0

    assert json.loads(capsys.readouterr().out) == {"host": "file-host", "retries": 7}


def test_invalid_format_fails_closed() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["show", "--format", "yaml"])

    assert excinfo.value.code != 0
