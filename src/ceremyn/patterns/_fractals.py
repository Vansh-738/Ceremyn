"""Shared fractal (windowed local-extreme) pivot detection.

Used by both the Higher-High swing-structure detector (`swing.py`) and the
Cup-and-Handle chart-shape detector (`chart_shape.py`). A "fractal" pivot (Bill
Williams' Fractals) is a bar whose value is the strict extreme within `window`
bars on both sides -- only confirmable `window` bars after the pivot itself.
Callers are responsible for treating `pivot_index + window`, not `pivot_index`,
as the moment the pivot is actually knowable.
"""

from decimal import Decimal


def pivot_highs(values: list[Decimal], window: int) -> list[int]:
    """Indices where `values[i]` exceeds every value within `window` bars on both sides."""
    return _pivots(values, window, high=True)


def pivot_lows(values: list[Decimal], window: int) -> list[int]:
    """Indices where `values[i]` is below every value within `window` bars on both sides."""
    return _pivots(values, window, high=False)


def _pivots(values: list[Decimal], window: int, *, high: bool) -> list[int]:
    n = len(values)
    pivots: list[int] = []
    for i in range(window, n - window):
        neighborhood = values[i - window : i] + values[i + 1 : i + 1 + window]
        if high:
            if all(values[i] > v for v in neighborhood):
                pivots.append(i)
        elif all(values[i] < v for v in neighborhood):
            pivots.append(i)
    return pivots
