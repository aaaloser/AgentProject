import click


def test_nested_help_heading_uses_all_indent_levels() -> None:
    formatter = click.HelpFormatter(indent_increment=3)
    formatter.indent()
    formatter.indent()
    formatter.write_heading("Commands")
    assert formatter.getvalue() == "      Commands:\n"
