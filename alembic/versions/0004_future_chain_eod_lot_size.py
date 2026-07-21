"""future_chain_eod: add lot_size

Same NSE per-underlying/periodic-revision caveat as 0003's
option_chain_eod.lot_size -- futures share the bhavcopy's NewBrdLotQty column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "future_chain_eod",
        sa.Column("lot_size", sa.BigInteger, nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("future_chain_eod", "lot_size")
