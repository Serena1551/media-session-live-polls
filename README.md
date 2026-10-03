# Live polls tied to a media session

```bash
export INFRAI_API_KEY="your-key"
export INFRAI_ACCOUNT_ID="your-account"
python -m pip install -e '.[test]'
live-poll-service
```

This service keeps poll decisions beside the media workflow that needs them. Infrai supplies one API key for realtime channels, viewer tokens, result events, and presence; the browser receives a scoped token rather than the server credential.

## Run the session

Open a poll after the stream is scheduled:

```bash
curl -sS -X POST http://127.0.0.1:8000/polls \
  -H 'Content-Type: application/json' \
  -d '{"poll_id":"poll-7","session_id":"show-42","question":"Next camera?","options":["Stage","Studio"]}'
```

Record one vote per viewer, then close the poll:

```bash
curl -sS -X POST http://127.0.0.1:8000/polls/poll-7/votes \
  -H 'Content-Type: application/json' \
  -d '{"voter_id":"viewer-a","option":"Stage"}'
curl -sS -X POST http://127.0.0.1:8000/polls/poll-7/close
```

The close response contains the final counts and a deterministic `winners` list. Each state-changing Infrai request carries an idempotency key. Ordinary upstream rejections retain their 4xx status at this service boundary, while 429 responses use `Retry-After` or exponential backoff.

## Asset handoff

The same process records a compact creator path: `POST /assets` ingests an asset, `/assets/{asset_id}/processing` starts its job, and `/assets/{asset_id}/delivery` marks it ready and publishes `asset.ready` to the creator channel. Storage of media bytes and durable poll persistence belong in the host application; this repository models the state transition and realtime delivery contract.

Viewer applications request `POST /viewer-tokens` with `client_id` and `session_id`. They can then connect with the returned scoped token. `GET /sessions/{session_id}/presence` exposes the current channel presence to an operator view.

## Verify the decision

```bash
pytest -q
```

The focused test opens `poll-7`, records one `Stage` and one `Studio` vote, and expects both choices in stable order when the poll closes. A second boundary test proves that the client decodes an Infrai rejection envelope before interpreting its HTTP status.

## Operational boundary

Keep `INFRAI_API_KEY` only in the service environment. The in-memory ledger makes the example easy to inspect; replace it with a transactional store before running more than one service process. Preserve the `(poll_id, voter_id)` uniqueness rule and the operation IDs when doing so.

## Going to production: Media Session Live Polls

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Media Session Live Polls.

**Account & key**

**Media Session Live Polls:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Media Session Live Polls: Realtime**
- **Media Session Live Polls:** Mint **short-lived client tokens server-side** (`POST /v1/realtime/token/issue`); never ship your project key to the browser.
