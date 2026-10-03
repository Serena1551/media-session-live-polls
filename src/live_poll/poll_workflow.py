from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from live_poll.infrai_realtime import InfraiRealtimeClient


class AssetStage(StrEnum):
    INGESTED = "ingested"
    PROCESSING = "processing"
    READY = "ready"


@dataclass
class MediaAsset:
    asset_id: str
    creator_id: str
    stage: AssetStage = AssetStage.INGESTED


@dataclass
class PollState:
    poll_id: str
    session_id: str
    question: str
    options: list[str]
    votes: dict[str, int] = field(default_factory=dict)
    closed: bool = False


class PollLedger:
    """Deterministic in-memory state for the example service."""

    def __init__(self, realtime: InfraiRealtimeClient, account_id: str) -> None:
        self._realtime = realtime
        self._account_id = account_id
        self.assets: dict[str, MediaAsset] = {}
        self.polls: dict[str, PollState] = {}
        self._voters: set[tuple[str, str]] = set()

    def ingest_asset(self, asset_id: str, creator_id: str) -> MediaAsset:
        asset = MediaAsset(asset_id=asset_id, creator_id=creator_id)
        self.assets[asset_id] = asset
        return asset

    def mark_processing(self, asset_id: str) -> MediaAsset:
        asset = self.assets[asset_id]
        asset.stage = AssetStage.PROCESSING
        return asset

    def deliver_asset(self, asset_id: str) -> MediaAsset:
        asset = self.assets[asset_id]
        asset.stage = AssetStage.READY
        self._realtime.publish(
            channel=f"creator:{asset.creator_id}",
            event="asset.ready",
            data={"asset_id": asset.asset_id, "stage": asset.stage},
            account_id=self._account_id,
            operation_id=f"asset-ready:{asset.asset_id}",
        )
        return asset

    def open_poll(
        self, poll_id: str, session_id: str, question: str, options: list[str]
    ) -> PollState:
        poll = PollState(poll_id, session_id, question, options)
        self.polls[poll_id] = poll
        self._realtime.create_channel(f"session:{session_id}")
        self._realtime.publish(
            channel=f"session:{session_id}",
            event="poll.opened",
            data={"poll_id": poll_id, "question": question, "options": list(options)},
            account_id=self._account_id,
            operation_id=f"poll-open:{poll_id}",
        )
        return poll

    def vote(self, poll_id: str, voter_id: str, option: str) -> dict[str, int]:
        poll = self.polls[poll_id]
        if poll.closed:
            raise ValueError("poll is closed")
        if option not in poll.options:
            raise ValueError("option is not on this poll")
        voter_key = (poll_id, voter_id)
        if voter_key in self._voters:
            raise ValueError("voter already recorded")
        self._voters.add(voter_key)
        poll.votes[option] = poll.votes.get(option, 0) + 1
        self._realtime.publish(
            channel=f"session:{poll.session_id}",
            event="poll.results",
            data={"poll_id": poll_id, "counts": dict(poll.votes)},
            account_id=self._account_id,
            operation_id=f"vote:{poll_id}:{voter_id}",
        )
        return dict(poll.votes)

    def close_poll(self, poll_id: str) -> dict[str, Any]:
        poll = self.polls[poll_id]
        poll.closed = True
        highest = max(poll.votes.values(), default=0)
        winners = sorted(option for option in poll.options if poll.votes.get(option, 0) == highest)
        result: dict[str, Any] = {
            "poll_id": poll_id,
            "counts": dict(poll.votes),
            "winners": winners,
        }
        self._realtime.publish(
            channel=f"session:{poll.session_id}",
            event="poll.closed",
            data=result,
            account_id=self._account_id,
            operation_id=f"poll-close:{poll_id}",
        )
        return result
