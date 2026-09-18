from config_cli.settings import resolve_settings


def test_cli_wins_over_env_file_and_default() -> None:
    settings = resolve_settings(
        cli={"host": "cli-host", "retries": 9},
        env={"host": "env-host", "retries": "8"},
        file={"host": "file-host", "retries": 7},
    )

    assert settings == {"host": "cli-host", "retries": 9}


def test_env_wins_over_file_and_default() -> None:
    settings = resolve_settings(
        cli={},
        env={"host": "env-host", "retries": "8"},
        file={"host": "file-host", "retries": 7},
    )

    assert settings == {"host": "env-host", "retries": 8}


def test_file_wins_over_default() -> None:
    settings = resolve_settings(cli={}, env={}, file={"host": "file-host", "retries": 7})

    assert settings == {"host": "file-host", "retries": 7}


def test_blank_values_do_not_override_a_valid_lower_layer() -> None:
    settings = resolve_settings(
        cli={"host": ""},
        env={"host": ""},
        file={"host": "file-host"},
    )

    assert settings["host"] == "file-host"
