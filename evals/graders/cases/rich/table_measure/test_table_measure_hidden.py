from rich import box
from rich.console import Console
from rich.measure import Measurement
from rich.table import Table


def measure(columns: int, *, show_edge: bool, fixed: bool = False) -> Measurement:
    console = Console(width=80, color_system=None, legacy_windows=False)
    table = Table(box=box.SIMPLE, show_edge=show_edge)
    for index in range(columns):
        table.add_column(f"column-{index}", width=8 if fixed else None, no_wrap=fixed)
    table.add_row(*(["alpha-value"] * columns))
    return Measurement.get(console, console.options, table)


def test_one_column_edge_width_is_two_columns_wider() -> None:
    edge = measure(1, show_edge=True)
    no_edge = measure(1, show_edge=False)
    assert edge.minimum - no_edge.minimum == 2
    assert edge.maximum - no_edge.maximum == 2


def test_three_columns_edge_width_is_two_columns_wider() -> None:
    edge = measure(3, show_edge=True)
    no_edge = measure(3, show_edge=False)
    assert edge.minimum - no_edge.minimum == 2
    assert edge.maximum - no_edge.maximum == 2


def test_fixed_width_no_wrap_preserves_two_column_edge_delta() -> None:
    edge = measure(3, show_edge=True, fixed=True)
    no_edge = measure(3, show_edge=False, fixed=True)
    assert edge.minimum - no_edge.minimum == 2
    assert edge.maximum - no_edge.maximum == 2
