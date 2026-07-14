"""Seed the instruments table from the Kite Connect NFO instrument dump.

Usage:
    .venv/bin/python scripts/seed_instruments.py --access-token <token>

Get an access token by completing the Kite login flow (the token is daily):
    print(KiteProvider.from_settings(get_settings()).login_url())
then exchange the request_token via KiteProvider.authenticate, or pass an
already-generated access token here.
"""

import argparse
import asyncio

from alphaquant.config import get_settings
from alphaquant.core.container import Container
from alphaquant.core.logging import configure_logging


async def main(access_token: str) -> None:
    settings = get_settings()
    configure_logging(settings)
    container = Container(settings)
    try:
        provider = container.kite_provider
        provider.set_access_token(access_token)
        contracts = await provider.fetch_option_contracts(settings.data.underlyings)
        stored = await container.instrument_repository.upsert_contracts(contracts)
        print(f"Stored {stored} option contracts for {', '.join(settings.data.underlyings)}.")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-token", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.access_token))
