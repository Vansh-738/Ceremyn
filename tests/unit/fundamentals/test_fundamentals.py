from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ceremyn.domain.fundamentals import FundamentalSnapshot
from ceremyn.fundamentals.provider import CSVFundamentalsProvider, JSONFundamentalsStore
from ceremyn.fundamentals.scoring import known_as_of, score

AS_OF = datetime(2026, 7, 1, tzinfo=UTC)


def filing(year: int, income: str = "10") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="TEST",
        period_type="annual",
        period_end=date(year, 3, 31),
        published_at=datetime(year, 5, 1, tzinfo=UTC),
        source="test filing",
        revenue=Decimal(100),
        net_income=Decimal(income),
        operating_cash_flow=Decimal(20),
        total_assets=Decimal(200),
        total_debt=Decimal(10),
        current_assets=Decimal(50),
        current_liabilities=Decimal(20),
        shares_outstanding=Decimal(10),
    )


def test_publication_and_restatement_are_point_in_time() -> None:
    old, new = filing(2025), filing(2026)
    revision = new.model_copy(
        update={"published_at": datetime(2026, 8, 1, tzinfo=UTC), "net_income": Decimal(-100)}
    )
    assert known_as_of([old, new, revision], "TEST", AS_OF) == (new, old)
    assert known_as_of([old, new, revision], "TEST", revision.published_at)[0] == revision
    assert score([old, new], "TEST", datetime(2026, 4, 1, tzinfo=UTC), Decimal(100)) is None
    assert score([old, new], "OTHER", AS_OF, Decimal(100)) is None


def test_scores_explain_missing_values_and_red_flags() -> None:
    current = filing(2026, "-10").model_copy(
        update={
            "operating_cash_flow": Decimal(-5),
            "promoter_pledge_pct": Decimal(30),
            "current_liabilities": None,
        }
    )
    result = score([filing(2025), current], "TEST", AS_OF, Decimal(100))
    assert result is not None
    assert "profitable" in result.checks_failed
    assert "current ratio improving" in result.checks_missing
    assert result.checks_run == 7
    assert len(result.red_flags) == 2
    assert result.earnings_yield == Decimal("-0.01")
    with pytest.raises(ValueError):
        score([current], "TEST", AS_OF, Decimal(0))
    assert score([filing(2024), current], "TEST", AS_OF, Decimal(100)) is None


def test_store_preserves_revisions_and_refuses_silent_overwrites(tmp_path: Path) -> None:
    store = JSONFundamentalsStore(tmp_path / "filings.json")
    assert store.history("TEST") == ()
    assert store.import_snapshots([filing(2025), filing(2026)]) == 2
    assert store.import_snapshots([filing(2026)]) == 0
    with pytest.raises(ValueError, match="restatement"):
        store.import_snapshots([filing(2026, "999")])
    assert JSONFundamentalsStore(store.path).history("test") == (filing(2025), filing(2026))


def test_csv_import_validates_publication_and_preserves_decimal(tmp_path: Path) -> None:
    path = tmp_path / "filings.csv"
    path.write_text(
        "symbol,period_type,period_end,published_at,source,revenue\n"
        "TEST,annual,2026-03-31,2026-05-01T00:00:00+00:00,fixture,123.45\n"
    )
    assert CSVFundamentalsProvider(path).history("TEST")[0].revenue == Decimal("123.45")
    bad = filing(2026).model_dump()
    bad["published_at"] = datetime(2026, 5, 1)  # deliberately naive
    with pytest.raises(ValidationError):
        FundamentalSnapshot.model_validate(bad)
    bad["published_at"] = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        FundamentalSnapshot.model_validate(bad)
