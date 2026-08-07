import pytest

from ceremyn.core.exceptions import DataError
from ceremyn.data.providers.nse_indices import parse_index_constituents

SAMPLE_CSV = (
    b"Company Name,Industry,Symbol,Series,ISIN Code\n"
    b"360 ONE WAM Ltd.,Financial Services,360ONE,EQ,INE466L01038\n"
    b"3M India Ltd.,Diversified,3MINDIA,EQ,INE470A01017\n"
    b"ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\n"
)


class TestParseIndexConstituents:
    def test_extracts_symbols(self) -> None:
        symbols = parse_index_constituents(SAMPLE_CSV)
        assert symbols == frozenset({"360ONE", "3MINDIA", "ABB"})

    def test_strips_whitespace(self) -> None:
        csv_bytes = b"Company Name,Industry,Symbol,Series,ISIN Code\nFoo,Bar, ABB ,EQ,ISIN\n"
        assert parse_index_constituents(csv_bytes) == frozenset({"ABB"})

    def test_handles_bom(self) -> None:
        symbols = parse_index_constituents(b"\xef\xbb\xbf" + SAMPLE_CSV)
        assert "360ONE" in symbols

    def test_empty_result_raises(self) -> None:
        with pytest.raises(DataError, match="zero symbols"):
            parse_index_constituents(b"Company Name,Industry,Symbol,Series,ISIN Code\n")

    def test_returns_frozenset(self) -> None:
        assert isinstance(parse_index_constituents(SAMPLE_CSV), frozenset)
