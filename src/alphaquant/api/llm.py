"""The LLM assistant's API — a separate router from `/dashboard` and `/execution`, mounted
independently in `api/app.py`. Every generating endpoint streams (Server-Sent Events); the
watchlist endpoints are plain synchronous CRUD against the session-local store (no model call
needed to add/remove a symbol — the `manage_watchlist` tool exists for when the user asks via
natural language chat instead).

Auth reuses the dashboard's existing bearer-token mechanism (`dashboard.permissions`) — see
`Permission.USE_LLM`.
"""

import json
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import (
    AuthError,
    ForbiddenError,
    Permission,
    Role,
    authorize,
    bearer_token,
)
from alphaquant.llm.assistant import Assistant, StreamEvent
from alphaquant.llm.watchlist import WatchlistStore


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SessionRequest(BaseModel):
    session_id: str = Field(min_length=1)


class GenerateReportRequest(BaseModel):
    session_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class CompareExperimentsRequest(BaseModel):
    session_id: str = Field(min_length=1)
    experiment_ids: list[str] = Field(min_length=1)


class WatchlistRequest(BaseModel):
    action: str = Field(pattern="^(add|remove)$")
    symbol: str = Field(min_length=1)


def _sse_encode(event: StreamEvent) -> str:
    payload: dict[str, object] = {"type": event.type}
    if event.text is not None:
        payload["text"] = event.text
    if event.name is not None:
        payload["name"] = event.name
    if event.source is not None:
        payload["source"] = event.source
    if event.citations:
        payload["citations"] = list(event.citations)
    if event.message is not None:
        payload["message"] = event.message
    return f"data: {json.dumps(payload)}\n\n"


async def _sse_stream(events: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield _sse_encode(event)


def _auth_dependency(
    permission: Permission, settings: DashboardSettings
) -> Callable[[str | None], Role]:
    def dependency(authorization: str | None = Header(default=None)) -> Role:
        token = bearer_token(authorization)
        try:
            return authorize(token, permission, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return dependency


def build_llm_router(
    assistant: Assistant, watchlist: WatchlistStore, settings: DashboardSettings
) -> APIRouter:
    router = APIRouter()
    use_llm = Depends(_auth_dependency(Permission.USE_LLM, settings))

    @router.post("/chat", dependencies=[use_llm])
    def chat(request: ChatRequest) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(assistant.chat(request.session_id, request.message)),
            media_type="text/event-stream",
        )

    @router.post("/reports/daily-recap", dependencies=[use_llm])
    def daily_recap(request: SessionRequest) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(assistant.daily_recap(request.session_id)),
            media_type="text/event-stream",
        )

    @router.post("/reports/session-recap", dependencies=[use_llm])
    def session_recap(request: SessionRequest) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(assistant.session_recap(request.session_id)),
            media_type="text/event-stream",
        )

    @router.post("/reports/generate", dependencies=[use_llm])
    def generate_report(request: GenerateReportRequest) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(assistant.generate_report(request.session_id, request.topic)),
            media_type="text/event-stream",
        )

    @router.post("/compare-experiments", dependencies=[use_llm])
    def compare_experiments(request: CompareExperimentsRequest) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(assistant.compare_experiments(request.session_id, request.experiment_ids)),
            media_type="text/event-stream",
        )

    @router.get("/watchlist/{session_id}", dependencies=[use_llm])
    def get_watchlist(session_id: str) -> dict[str, object]:
        return watchlist.list(session_id).model_dump(mode="json")

    @router.post("/watchlist/{session_id}", dependencies=[use_llm])
    def update_watchlist(session_id: str, request: WatchlistRequest) -> dict[str, object]:
        if request.action == "add":
            snapshot = watchlist.add(session_id, request.symbol)
        else:
            snapshot = watchlist.remove(session_id, request.symbol)
        return snapshot.model_dump(mode="json")

    return router
