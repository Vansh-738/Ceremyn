"""Uvicorn entrypoint: `uvicorn alphaquant.api.main:app`."""

from alphaquant.api.app import create_app

app = create_app()
