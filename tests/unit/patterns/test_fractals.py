from decimal import Decimal

from ceremyn.patterns._fractals import pivot_highs, pivot_lows


def _d(values: list[float]) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


class TestPivotHighs:
    def test_single_clear_peak(self) -> None:
        values = _d([1, 2, 3, 5, 3, 2, 1])
        assert pivot_highs(values, 2) == [3]

    def test_no_pivot_on_monotonic_series(self) -> None:
        values = _d([1, 2, 3, 4, 5, 6, 7])
        assert pivot_highs(values, 2) == []

    def test_equal_neighbor_is_not_a_pivot(self) -> None:
        # Strict inequality only -- a tie must not count as a pivot.
        values = _d([1, 2, 5, 5, 2, 1])
        assert pivot_highs(values, 2) == []

    def test_too_short_for_window_returns_empty(self) -> None:
        assert pivot_highs(_d([1, 5, 1]), 2) == []


class TestPivotLows:
    def test_single_clear_trough(self) -> None:
        values = _d([5, 4, 3, 1, 3, 4, 5])
        assert pivot_lows(values, 2) == [3]

    def test_no_pivot_on_monotonic_series(self) -> None:
        values = _d([7, 6, 5, 4, 3, 2, 1])
        assert pivot_lows(values, 2) == []
