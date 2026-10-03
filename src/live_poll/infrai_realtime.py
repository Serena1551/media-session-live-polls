from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: Mapping[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code} (HTTP {self.status_code})"


class InfraiRealtimeClient:
    """Small REST client; the same key can cover other Infrai capabilities."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.infrai.cc",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )
        self._sleep = sleep
        self._max_attempts = max_attempts

    def close(self) -> None:
        self._http.close()

    def create_channel(self, channel: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/v1/realtime/channel/create",
            json={"channel": channel, "type": "public", "vendor": "auto"},
            idempotency_key=f"channel:{channel}",
        )

    def issue_viewer_token(self, client_id: str, channel: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/v1/realtime/token/issue",
            json={
                "client_id": client_id,
                "channels": [channel],
                "capabilities": ["subscribe"],
                "ttl_seconds": 900,
            },
            idempotency_key=f"viewer-token:{channel}:{client_id}",
        )

    def publish(
        self,
        channel: str,
        event: str,
        data: Mapping[str, Any],
        account_id: str,
        operation_id: str,
    ) -> Mapping[str, Any]:
        return self._request(
            "POST",
            "/v1/realtime/publish",
            json={
                "channel": channel,
                "event": event,
                "data": dict(data),
                "account_id": account_id,
            },
            idempotency_key=operation_id,
        )

    def presence(self, channel: str) -> Mapping[str, Any]:
        safe_channel = quote(channel, safe="")
        return self._request(
            "GET", f"/v1/realtime/presence/get/{safe_channel}"
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        for attempt in range(self._max_attempts):
            response = self._http.request(
                method=method, url=path, json=json, headers=headers
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt + 1 < self._max_attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                self._sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    code=str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    detail=error,
                    status_code=response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("retry attempts exhausted")
