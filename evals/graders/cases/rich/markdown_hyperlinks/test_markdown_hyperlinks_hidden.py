from io import StringIO

from rich.console import Console
from rich.markdown import Markdown


def render_markdown(markup: str, *, hyperlinks: bool) -> str:
    stream = StringIO()
    Console(file=stream, width=80, color_system=None, legacy_windows=False).print(
        Markdown(markup, hyperlinks=hyperlinks)
    )
    return stream.getvalue()


def test_multiple_disabled_links_keep_each_destination_visible() -> None:
    output = render_markdown("[one](https://one.example) and [two](https://two.example)", hyperlinks=False)
    assert "https://one.example" in output
    assert "https://two.example" in output


def test_disabled_link_destination_survives_punctuation() -> None:
    output = render_markdown("Before ([docs](https://docs.example/path?q=1)), after.", hyperlinks=False)
    assert "https://docs.example/path?q=1" in output


def test_disabled_image_and_link_mix_keeps_destinations_visible() -> None:
    output = render_markdown(
        "![diagram](https://images.example/diagram.png) and [docs](https://docs.example/guide)",
        hyperlinks=False,
    )
    assert "diagram" in output
    assert "https://docs.example/guide" in output
