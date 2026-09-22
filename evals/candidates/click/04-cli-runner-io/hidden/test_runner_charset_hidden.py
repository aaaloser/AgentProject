import click
from click.testing import CliRunner


def test_result_output_decodes_cp1252_bytes_with_runner_charset() -> None:
    cli = click.Command("cli", callback=lambda: click.echo("€"))
    result = CliRunner(charset="cp1252").invoke(cli)
    assert result.exit_code == 0, result.output
    assert result.output == "€\n"
