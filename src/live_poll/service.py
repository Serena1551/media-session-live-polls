from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from live_poll.infrai_realtime import InfraiError, InfraiRealtimeClient
from live_poll.poll_workflow import PollLedger


class AssetIngestRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    creator_id: str = Field(min_length=1)


class PollOpenRequest(BaseModel):
    poll_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=8)


class VoteRequest(BaseModel):
    voter_id: str = Field(min_length=1)
    option: str = Field(min_length=1)


class ViewerTokenRequest(BaseModel):
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


def build_app(ledger: PollLedger, realtime: InfraiRealtimeClient) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        realtime.close()

    app = FastAPI(title="Media session live polls", lifespan=lifespan)

    def get_ledger() -> PollLedger:
        return ledger

    @app.exception_handler(InfraiError)
    async def infrai_rejection(_: Request, exc: InfraiError) -> JSONResponse:
        caller_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return JSONResponse(
            status_code=caller_status,
            content={"error": {"code": exc.code, "detail": dict(exc.detail)}},
        )

    @app.post("/assets", status_code=201)
    def ingest_asset(body: AssetIngestRequest, state: PollLedger = Depends(get_ledger)) -> Any:
        return state.ingest_asset(body.asset_id, body.creator_id)

    @app.post("/assets/{asset_id}/processing")
    def process_asset(asset_id: str, state: PollLedger = Depends(get_ledger)) -> Any:
        return state.mark_processing(asset_id)

    @app.post("/assets/{asset_id}/delivery")
    def deliver_asset(asset_id: str, state: PollLedger = Depends(get_ledger)) -> Any:
        return state.deliver_asset(asset_id)

    @app.post("/polls", status_code=201)
    def open_poll(body: PollOpenRequest, state: PollLedger = Depends(get_ledger)) -> Any:
        return state.open_poll(
            body.poll_id, body.session_id, body.question, body.options
        )

    @app.post("/polls/{poll_id}/votes")
    def cast_vote(poll_id: str, body: VoteRequest, state: PollLedger = Depends(get_ledger)) -> Any:
        try:
            return {"counts": state.vote(poll_id, body.voter_id, body.option)}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/polls/{poll_id}/close")
    def close_poll(poll_id: str, state: PollLedger = Depends(get_ledger)) -> Any:
        return state.close_poll(poll_id)

    @app.post("/viewer-tokens")
    def viewer_token(body: ViewerTokenRequest) -> Any:
        return realtime.issue_viewer_token(
            body.client_id, f"session:{body.session_id}"
        )

    @app.get("/sessions/{session_id}/presence")
    def session_presence(session_id: str) -> Any:
        return realtime.presence(f"session:{session_id}")

    return app


def create_app() -> FastAPI:
    realtime = InfraiRealtimeClient(os.environ["INFRAI_API_KEY"])
    ledger = PollLedger(realtime, os.environ["INFRAI_ACCOUNT_ID"])
    return build_app(ledger, realtime)


def run() -> None:
    uvicorn.run("live_poll.service:create_app", factory=True, host="127.0.0.1", port=8000)
