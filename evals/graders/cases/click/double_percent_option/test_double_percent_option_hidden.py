import click
from click.testing import CliRunner


def test_repeated_percent_prefix_preserves_the_option_name() -> None:
    cli = click.Command(
        "cli",
        params=[click.Option(["%%trace"], is_flag=True)],
        callback=lambda trace: click.echo(f"trace={trace}"),
    )
    result = CliRunner().invoke(cli, ["%%trace"])
    assert result.exit_code == 0, result.output
    assert result.output == "trace=True\n"
