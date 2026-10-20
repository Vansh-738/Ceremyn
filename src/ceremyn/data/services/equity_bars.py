"""Build completed-bar contexts using only corporate actions effective by each bar."""

from datetime import datetime
from decimal import Decimal

from ceremyn.core.timeutils import to_ist
from ceremyn.domain import Candle, CorporateAction, CorporateActionType, EquityInstrument
from ceremyn.domain.fundamentals import FundamentalSnapshot
from ceremyn.fundamentals.scoring import score
from ceremyn.patterns.ranking import detect_patterns
from ceremyn.strategies.bars import BarContext


def adjusted_history(
    candles: tuple[Candle, ...], actions: tuple[CorporateAction, ...], as_of: datetime
) -> tuple[Candle, ...]:
    """Split/bonus-adjust historical OHLCV, without using future effective actions.

    Cash dividends remain price moves; the backtest books their cash separately.
    The caller must provide complete corporate-action records for the dataset.
    """
    output = []
    for candle in candles:
        if candle.timestamp > as_of:
            continue
        ratio = Decimal(1)
        for action in actions:
            if (
                action.tradingsymbol == candle.tradingsymbol
                and action.ratio is not None
                and action.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS)
                and to_ist(candle.timestamp).date() < action.ex_date <= to_ist(as_of).date()
            ):
                ratio *= action.ratio
        output.append(
            candle.model_copy(
                update={
                    "open": candle.open / ratio,
                    "high": candle.high / ratio,
                    "low": candle.low / ratio,
                    "close": candle.close / ratio,
                    "volume": int(candle.volume * ratio),
                }
            )
        )
    return tuple(output)


def bar_context(
    instrument: EquityInstrument,
    candles: tuple[Candle, ...],
    actions: tuple[CorporateAction, ...] = (),
    filings: tuple[FundamentalSnapshot, ...] = (),
) -> BarContext:
    if not candles:
        raise ValueError("candles are required")
    at = candles[-1].timestamp
    adjusted = adjusted_history(candles, actions, at)
    return BarContext(
        as_of=at,
        instrument=instrument,
        candles=adjusted,
        patterns=detect_patterns(adjusted, instrument.tradingsymbol),
        fundamentals=score(filings, instrument.tradingsymbol, at, candles[-1].close),
    )
