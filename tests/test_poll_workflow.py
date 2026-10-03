from typing import Any

import httpx
from fastapi.testclient import TestClient

from live_poll.infrai_realtime import InfraiError, InfraiRealtimeClient
from live_poll.poll_workflow import PollLedger
from live_poll.service import build_app


class RecordingRealtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any], str]] = []

    def close(self) -> None:
        pass

    def create_channel(self, channel: str) -> dict[str, str]:
        return {"channel": channel}

    def publish(
        self,
        channel: str,
        event: str,
        data: dict[str, Any],
        account_id: str,
        operation_id: str,
    ) -> dict[str, bool]:
        self.events.append((channel, event, data, operation_id))
        return {"accepted": True}


def test_close_poll_reports_a_tie_in_stable_option_order() -> None:
    realtime = RecordingRealtime()
    ledger = PollLedger(realtime, "acct-media")  # type: ignore[arg-type]
    ledger.open_poll("poll-7", "show-42", "Next camera?", ["Stage", "Studio"])
    ledger.vote("poll-7", "viewer-a", "Studio")
    ledger.vote("poll-7", "viewer-b", "Stage")

    result = ledger.close_poll("poll-7")

    assert result == {
        "poll_id": "poll-7",
        "counts": {"Studio": 1, "Stage": 1},
        "winners": ["Stage", "Studio"],
    }
    assert realtime.events[-1][1:] == (
        "poll.closed",
        result,
        "poll-close:poll-7",
    )


def test_client_decodes_business_rejection_before_http_status() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["Idempotency-Key"] == "channel:session:show-42"
        return httpx.Response(
            400,
            json={
                "ok": False,
                "data": None,
                "error": {"code": "INVALID_ARGUMENT", "message": "bad channel"},
                "metadata": {},
            },
        )

    client = InfraiRealtimeClient("test-key", transport=httpx.MockTransport(reject))
    try:
        client.create_channel("session:show-42")
    except InfraiError as exc:
        assert exc.code == "INVALID_ARGUMENT"
        assert exc.status_code == 400
    else:
        raise AssertionError("expected InfraiError")
    finally:
        client.close()


def test_assembled_routes_inject_ledger_without_state_query() -> None:
    realtime = RecordingRealtime()
    ledger = PollLedger(realtime, "acct-media")  # type: ignore[arg-type]
    with TestClient(build_app(ledger, realtime)) as client:  # type: ignore[arg-type]
        assert client.post("/assets", json={"asset_id": "a", "creator_id": "c"}).status_code == 201
        assert client.post("/assets/a/processing").status_code == 200
        assert client.post("/assets/a/delivery").status_code == 200
        assert client.post("/polls", json={
            "poll_id": "p", "session_id": "s", "question": "Which?", "options": ["A", "B"]
        }).status_code == 201
        assert client.post("/polls/p/votes", json={"voter_id": "v", "option": "A"}).status_code == 200
        assert client.post("/polls/p/close").status_code == 200
