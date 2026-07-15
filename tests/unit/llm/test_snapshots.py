from datetime import UTC, datetime

import pytest

from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief, StrategyCatalogEntry

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
NAIVE = datetime(2026, 7, 15, 10, 0)


def test_experiment_detail_brief_defaults() -> None:
    brief = ExperimentDetailBrief(experiment_id="e1", strategy_name="Short Strangle", timestamp=NOW)
    assert brief.sharpe == 0.0
    assert brief.parameters == {}
    assert brief.trade_count == 0


def test_experiment_detail_brief_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="aware"):
        ExperimentDetailBrief(experiment_id="e1", strategy_name="s", timestamp=NAIVE)


def test_experiment_detail_brief_is_frozen() -> None:
    brief = ExperimentDetailBrief(experiment_id="e1", strategy_name="s", timestamp=NOW)
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError on frozen assignment
        brief.sharpe = 1.0  # type: ignore[misc]


def test_recap_brief_defaults() -> None:
    recap = RecapBrief(window_label="today", window_start=NOW, window_end=NOW)
    assert recap.notable_events == ()
    assert recap.net_pnl == 0.0


def test_recap_brief_rejects_naive_window_start() -> None:
    with pytest.raises(ValueError, match="aware"):
        RecapBrief(window_label="today", window_start=NAIVE, window_end=NOW)


def test_recap_brief_rejects_naive_window_end() -> None:
    with pytest.raises(ValueError, match="aware"):
        RecapBrief(window_label="today", window_start=NOW, window_end=NAIVE)


def test_strategy_catalog_entry_defaults() -> None:
    entry = StrategyCatalogEntry(strategy_type="short_strangle", class_name="ShortStrangle")
    assert entry.description == ""
