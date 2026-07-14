"""Black-Scholes pricing, greeks, and implied volatility for European index options.

Conventions:
- Continuously compounded risk-free rate, zero dividend yield (index options).
- Time to expiry in years, ACT/365.
- theta is per calendar day; vega and rho are per 1 percentage point.
- Floats throughout: this is the numerical kernel (see CLAUDE.md); money stays
  Decimal outside it.

Validated in tests against standard published values
(S=100, K=100, T=1, r=5%, sigma=20%).
"""

import math
from dataclasses import dataclass

from scipy.optimize import brentq

from alphaquant.domain import Greeks

_SQRT_2 = math.sqrt(2.0)
_DAYS_PER_YEAR = 365.0

# brentq bracket for annualized volatility: 0.1% to 500%.
_IV_LO, _IV_HI = 0.001, 5.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class _D1D2:
    d1: float
    d2: float


def _d1d2(spot: float, strike: float, t: float, r: float, sigma: float) -> _D1D2:
    sig_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / sig_sqrt_t
    return _D1D2(d1=d1, d2=d1 - sig_sqrt_t)


def bs_price(spot: float, strike: float, t: float, r: float, sigma: float, is_call: bool) -> float:
    """Black-Scholes price. For t <= 0 returns intrinsic value."""
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if t <= 0:
        return max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if sigma <= 0:
        # Deterministic forward: price is discounted intrinsic on the forward.
        forward = spot * math.exp(r * t)
        intrinsic = max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
        return math.exp(-r * t) * intrinsic
    d = _d1d2(spot, strike, t, r, sigma)
    df = math.exp(-r * t)
    if is_call:
        price = spot * _norm_cdf(d.d1) - strike * df * _norm_cdf(d.d2)
    else:
        price = strike * df * _norm_cdf(-d.d2) - spot * _norm_cdf(-d.d1)
    # Floating-point cancellation can produce a tiny negative value for far OTM
    # options close to expiry; clamp to the no-arbitrage floor.
    return max(price, 0.0)


def bs_greeks(
    spot: float, strike: float, t: float, r: float, sigma: float, is_call: bool
) -> Greeks:
    """Greeks; iv field carries the sigma used for the computation."""
    if t <= 0 or sigma <= 0:
        # Expired or degenerate: delta is a step function, everything else 0.
        delta = (1.0 if spot > strike else 0.0) if is_call else -1.0 if spot < strike else 0.0
        return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, iv=None)

    d = _d1d2(spot, strike, t, r, sigma)
    df = math.exp(-r * t)
    pdf_d1 = _norm_pdf(d.d1)
    sqrt_t = math.sqrt(t)

    delta = _norm_cdf(d.d1) if is_call else _norm_cdf(d.d1) - 1.0
    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega_annual = spot * pdf_d1 * sqrt_t
    if is_call:
        theta_annual = -spot * pdf_d1 * sigma / (2 * sqrt_t) - r * strike * df * _norm_cdf(d.d2)
        rho_annual = strike * t * df * _norm_cdf(d.d2)
    else:
        theta_annual = -spot * pdf_d1 * sigma / (2 * sqrt_t) + r * strike * df * _norm_cdf(-d.d2)
        rho_annual = -strike * t * df * _norm_cdf(-d.d2)

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta_annual / _DAYS_PER_YEAR,
        vega=vega_annual / 100.0,
        rho=rho_annual / 100.0,
        iv=sigma,
    )


def implied_vol(
    price: float, spot: float, strike: float, t: float, r: float, is_call: bool
) -> float | None:
    """Implied volatility via Brent's method; None when no vol reproduces `price`.

    Returns None (rather than raising) for prices outside no-arbitrage bounds —
    common in stale or wide EOD marks for illiquid strikes.
    """
    if t <= 0 or price <= 0:
        return None
    lo = bs_price(spot, strike, t, r, _IV_LO, is_call)
    hi = bs_price(spot, strike, t, r, _IV_HI, is_call)
    if not (lo <= price <= hi):
        return None

    def objective(sigma: float) -> float:
        return bs_price(spot, strike, t, r, sigma, is_call) - price

    result: float = brentq(objective, _IV_LO, _IV_HI, xtol=1e-8, maxiter=200)
    return result


def time_to_expiry_years(seconds: float) -> float:
    """ACT/365 year fraction from a positive interval in seconds."""
    return max(seconds, 0.0) / (_DAYS_PER_YEAR * 24 * 3600)
