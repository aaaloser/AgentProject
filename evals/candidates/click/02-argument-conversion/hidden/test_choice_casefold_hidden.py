import click
from click.testing import CliRunner


def test_case_insensitive_choice_returns_original_unicode_value() -> None:
    cli = click.Command(
        "cli",
        params=[click.Argument(["word"], type=click.Choice(["weiß"], case_sensitive=False))],
        callback=lambda word: click.echo(word),
    )
    result = CliRunner().invoke(cli, ["WEISS"])
    assert result.exit_code == 0, result.output
    assert result.output == "weiß\n"
