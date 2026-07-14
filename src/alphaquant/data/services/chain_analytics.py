"""Option-chain analytics: greeks/IV enrichment, IV rank, max pain.

PCR and OI totals live on the OptionChainSnapshot domain model itself; this
service adds everything that needs the pricing kernel or history.
"""

from datetime import datetime, time
from decimal import Decimal

from alphaquant.core.timeutils import IST
from alphaquant.data.services.pricing import bs_greeks, implied_vol, time_to_expiry_years
from alphaquant.domain import ChainEntry, OptionChainSnapshot

EXPIRY_CUTOFF = time(15, 30)  # options expire at the close of the expiry day


def expiry_moment(snapshot: OptionChainSnapshot) -> datetime:
    return datetime.combine(snapshot.expiry, EXPIRY_CUTOFF, tzinfo=IST)


class ChainAnalyticsService:
    def __init__(self, risk_free_rate: float) -> None:
        self._r = risk_free_rate

    def enrich(self, snapshot: OptionChainSnapshot) -> OptionChainSnapshot:
        """Attach IV + greeks to every entry that has a usable price."""
        t = time_to_expiry_years(
            (expiry_moment(snapshot) - snapshot.timestamp).total_seconds()
        )
        spot = float(snapshot.spot)
        entries: list[ChainEntry] = []
        for entry in snapshot.entries:
            price = _mark_price(entry)
            if price is None or t <= 0:
                entries.append(entry)
                continue
            contract = entry.contract
            iv = implied_vol(price, spot, float(contract.strike), t, self._r, contract.is_call)
            if iv is None:
                entries.append(entry)
                continue
            greeks = bs_greeks(spot, float(contract.strike), t, self._r, iv, contract.is_call)
            entries.append(entry.model_copy(update={"greeks": greeks}))
        return snapshot.model_copy(update={"entries": tuple(entries)})

    def atm_iv(self, snapshot: OptionChainSnapshot) -> float | None:
        """Mean of the ATM call/put IVs (the usual scalar 'chain IV')."""
        atm = snapshot.atm_strike
        ivs = [
            entry.greeks.iv
            for entry in snapshot.entries
            if entry.contract.strike == atm and entry.greeks is not None and entry.greeks.iv
        ]
        return sum(ivs) / len(ivs) if ivs else None


def iv_rank(current: float, history: list[float]) -> float | None:
    """Position of `current` within the historical min..max range, 0..100."""
    if len(history) < 2:
        return None
    lo, hi = min(history), max(history)
    if hi == lo:
        return None
    return max(0.0, min(100.0, (current - lo) / (hi - lo) * 100.0))


def iv_percentile(current: float, history: list[float]) -> float | None:
    """Share of historical observations strictly below `current`, 0..100."""
    if not history:
        return None
    below = sum(1 for value in history if value < current)
    return below / len(history) * 100.0


def max_pain(snapshot: OptionChainSnapshot) -> Decimal:
    """Strike where option writers' total payout at expiry is minimal."""
    strikes = snapshot.strikes
    best_strike = strikes[0]
    best_payout: Decimal | None = None
    for settle in strikes:
        payout = Decimal(0)
        for entry in snapshot.entries:
            strike = entry.contract.strike
            oi = entry.open_interest
            if entry.contract.is_call and settle > strike:
                payout += (settle - strike) * oi
            elif entry.contract.is_put and settle < strike:
                payout += (strike - settle) * oi
        if best_payout is None or payout < best_payout:
            best_strike, best_payout = settle, payout
    return best_strike


def _mark_price(entry: ChainEntry) -> float | None:
    """Mid if both sides quoted, else last traded price; None if unusable."""
    quote = entry.quote
    if quote is None:
        return None
    mid = quote.mid
    if mid is not None and mid > 0:
        return float(mid)
    return float(quote.last_price) if quote.last_price > 0 else None
