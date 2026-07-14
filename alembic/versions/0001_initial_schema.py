"""initial schema: instruments, candles, option_chain_eod, chain_snapshot_entries

Revision ID: 0001
Revises:
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE = sa.Numeric(14, 4)


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tradingsymbol", sa.Text, nullable=False, unique=True),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("underlying", sa.Text),
        sa.Column("expiry", sa.Date),
        sa.Column("strike", sa.Numeric(12, 2)),
        sa.Column("option_type", sa.Text),
        sa.Column("lot_size", sa.BigInteger),
        sa.Column("tick_size", sa.Numeric(8, 4), nullable=False, server_default="0.05"),
        sa.Column("broker_token", sa.BigInteger),
    )
    op.create_index("ix_instruments_underlying_expiry", "instruments", ["underlying", "expiry"])

    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tradingsymbol", sa.Text, nullable=False),
        sa.Column("timeframe", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("open_interest", sa.BigInteger, nullable=False, server_default="0"),
        sa.UniqueConstraint("tradingsymbol", "timeframe", "ts", name="uq_candles_symbol_tf_ts"),
    )

    op.create_table(
        "option_chain_eod",
        sa.Column("trade_date", sa.Date, primary_key=True),
        sa.Column("underlying", sa.Text, primary_key=True),
        sa.Column("expiry", sa.Date, primary_key=True),
        sa.Column("strike", sa.Numeric(12, 2), primary_key=True),
        sa.Column("option_type", sa.Text, primary_key=True),
        sa.Column("open", PRICE),
        sa.Column("high", PRICE),
        sa.Column("low", PRICE),
        sa.Column("close", PRICE),
        sa.Column("settle", PRICE),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("open_interest", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("oi_change", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("underlying_close", PRICE),
    )
    op.create_index(
        "ix_chain_eod_underlying_date", "option_chain_eod", ["underlying", "trade_date"]
    )

    op.create_table(
        "chain_snapshot_entries",
        sa.Column("captured_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("underlying", sa.Text, primary_key=True),
        sa.Column("expiry", sa.Date, primary_key=True),
        sa.Column("strike", sa.Numeric(12, 2), primary_key=True),
        sa.Column("option_type", sa.Text, primary_key=True),
        sa.Column("spot", PRICE, nullable=False),
        sa.Column("last_price", PRICE),
        sa.Column("bid", PRICE),
        sa.Column("ask", PRICE),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("open_interest", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("iv", sa.Float),
    )


def downgrade() -> None:
    op.drop_table("chain_snapshot_entries")
    op.drop_index("ix_chain_eod_underlying_date", table_name="option_chain_eod")
    op.drop_table("option_chain_eod")
    op.drop_table("candles")
    op.drop_index("ix_instruments_underlying_expiry", table_name="instruments")
    op.drop_table("instruments")
