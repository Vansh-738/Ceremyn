"""One-command Kite login: exchange today's login for an access token.

Zerodha requires a fresh login once per trading day — this is Zerodha's own
security rule, not something any code can skip. Run this each morning before
paper/live trading.

What it does:
    1. Prints a Kite login URL.
    2. You open it, sign in with your Zerodha password + 2FA.
    3. Kite redirects your browser to the Redirect URL you set when creating
       the app, with a `request_token=...` in the address bar. Copy just that
       token (it expires within minutes) and paste it back here.
    4. This script exchanges it for an access token and writes it straight
       into your .env file — it is never printed to the terminal or sent
       anywhere else.

Usage:
    .venv/bin/python scripts/kite_login.py
"""

import re
from pathlib import Path

from alphaquant.config import get_settings
from alphaquant.core.exceptions import BrokerError
from alphaquant.data.providers.kite import KiteProvider

ENV_PATH = Path(".env")
ENV_KEY = "ALPHAQUANT_KITE__ACCESS_TOKEN"


def _write_access_token(token: str) -> None:
    """Update (or add) the access-token line in .env — never printed, never logged."""
    if not ENV_PATH.exists():
        raise SystemExit(
            f"{ENV_PATH.resolve()} does not exist — create it from .env.example first."
        )
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^{re.escape(ENV_KEY)}=")
    new_line = f"{ENV_KEY}={token}"
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = new_line
            break
    else:
        lines.append(new_line)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import asyncio

    settings = get_settings()
    if not settings.kite.api_key:
        raise SystemExit("ALPHAQUANT_KITE__API_KEY is not set in .env — set that first.")
    api_secret = settings.kite.api_secret.get_secret_value()
    if not api_secret:
        raise SystemExit("ALPHAQUANT_KITE__API_SECRET is not set in .env — set that first.")

    provider = KiteProvider.from_settings(settings)
    print("1. Open this URL in your browser and log in to Kite:\n")
    print(f"   {provider.login_url()}\n")
    print("2. After logging in, your browser will redirect somewhere (it may look like an")
    print("   error page — that's expected). Look at the address bar for request_token=...")
    print("   and copy everything between '=' and the next '&'.\n")
    request_token = input("Paste the request_token here: ").strip()
    if not request_token:
        raise SystemExit("No request_token entered — aborting.")

    try:
        access_token = asyncio.run(provider.authenticate(request_token, api_secret))
    except BrokerError as exc:
        raise SystemExit(
            f"Kite login exchange failed: {exc}\n"
            "The request_token expires within minutes of logging in — try again from step 1."
        ) from exc

    _write_access_token(access_token)
    print("\nDone — access token saved to .env. It's valid until Kite's next daily reset.")


if __name__ == "__main__":
    main()
