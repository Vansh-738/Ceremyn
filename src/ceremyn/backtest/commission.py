"""Indian transaction cost model."""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.domain.enums import Side

PAISE = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


class IndianCostConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    brokerage_per_order: Decimal = Field(default=Decimal("20"), ge=0)
    stt_sell_rate: Decimal = Field(default=Decimal("0.0005"), ge=0)
    exchange_txn_rate: Decimal = Field(default=Decimal("0.00053"), ge=0)
    gst_rate: Decimal = Field(default=Decimal("0.18"), ge=0)
    sebi_rate: Decimal = Field(default=Decimal("0.000001"), ge=0)
    stamp_duty_buy_rate: Decimal = Field(default=Decimal("0.00003"), ge=0)


class CostBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    brokerage: Decimal = Decimal("0")
    stt: Decimal = Decimal("0")
    exchange_transaction_charges: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    sebi_charges: Decimal = Decimal("0")
    stamp_duty: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return _money(
            self.brokerage
            + self.stt
            + self.exchange_transaction_charges
            + self.gst
            + self.sebi_charges
            + self.stamp_duty
        )


class IndianCostModel:
    def __init__(self, config: IndianCostConfig | None = None) -> None:
        self.config = config or IndianCostConfig()

    def calculate(self, *, side: Side, quantity: int, price: Decimal) -> CostBreakdown:
        turnover = price * quantity
        brokerage = _money(self.config.brokerage_per_order)
        stt = _money(turnover * self.config.stt_sell_rate) if side is Side.SELL else Decimal("0")
        exchange = _money(turnover * self.config.exchange_txn_rate)
        gst = _money((brokerage + exchange) * self.config.gst_rate)
        sebi = _money(turnover * self.config.sebi_rate)
        stamp = (
            _money(turnover * self.config.stamp_duty_buy_rate) if side is Side.BUY else Decimal("0")
        )
        return CostBreakdown(
            brokerage=brokerage,
            stt=stt,
            exchange_transaction_charges=exchange,
            gst=gst,
            sebi_charges=sebi,
            stamp_duty=stamp,
        )
