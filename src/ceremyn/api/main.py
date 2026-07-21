"""Uvicorn entrypoint: `uvicorn ceremyn.api.main:app`."""

from ceremyn.api.app import create_app

app = create_app()
