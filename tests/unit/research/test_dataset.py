import pytest
from pydantic import ValidationError

from ceremyn.research.dataset import Dataset, dataset_from_events
from tests.unit.research.conftest import price_path_events


def test_market_data_version_is_deterministic() -> None:
    events = price_path_events(["100", "110", "120"])
    a = Dataset(name="d", events=events)
    b = Dataset(name="d", events=events)
    assert a.market_data_version == b.market_data_version
    assert len(a.market_data_version) == 64  # sha256 hexdigest


def test_market_data_version_changes_with_data() -> None:
    a = Dataset(name="d", events=price_path_events(["100", "110"]))
    b = Dataset(name="d", events=price_path_events(["100", "111"]))
    assert a.market_data_version != b.market_data_version


def test_version_independent_of_event_order() -> None:
    events = price_path_events(["100", "110", "120"])
    forward = Dataset(name="d", events=events)
    reversed_ds = Dataset(name="d", events=tuple(reversed(events)))
    assert forward.market_data_version == reversed_ds.market_data_version


def test_ordered_events_sorted_by_timestamp() -> None:
    events = price_path_events(["100", "110", "120"])
    ds = Dataset(name="d", events=tuple(reversed(events)))
    ordered = ds.ordered_events()
    assert [e.timestamp for e in ordered] == sorted(e.timestamp for e in events)


def test_size_and_helper() -> None:
    ds = dataset_from_events("d", price_path_events(["1", "2", "3"]), feature_version="v2")
    assert ds.size == 3
    assert ds.feature_version == "v2"


def test_empty_events_rejected() -> None:
    with pytest.raises(ValidationError):
        Dataset(name="d", events=())
