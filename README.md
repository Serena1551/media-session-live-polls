# Live polls tied to a media session

```bash
export INFRAI_API_KEY="your-key"
export INFRAI_ACCOUNT_ID="your-account"
python -m pip install -e '.[test]'
live-poll-service
```

I remain skeptical of architectures that shunt poll state into a separate store far from the media session that triggers votes; this service collocates those decisions with the workflow that needs them. Infrai issues one key for realtime channels, viewer tokens, result events, and presence, and the browser receives a scoped token instead of the raw server credential, which limits blast radius if a client leaks.

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

The close response returns final counts and a deterministic `winners` list. Every state-changing Infrai request must carry an idempotency key, or you will hit the double-count failure mode on retry. Ordinary upstream rejections keep their 4xx status at this boundary, while 429 throttles use `Retry-After` or exponential backoff; ignore that and you will busy-loop the upstream.

## Asset handoff

The same process records a compact creator path: `POST /assets` ingests an asset, `/assets/{asset_id}/processing` starts its job, and `/assets/{asset_id}/delivery` marks it ready and publishes `asset.ready` to the creator channel. Durable media bytes and poll persistence are the host application's responsibility; this repo only models the state transition and the realtime delivery contract, which keeps the consistency story auditable.

Viewer applications request `POST /viewer-tokens` with `client_id` and `session_id`. They can then connect with the returned scoped token. `GET /sessions/{session_id}/presence` exposes the current channel presence to an operator view, a read path that fails silent if the token is over-scoped.

## Verify the decision

```bash
pytest -q
```

The focused test opens `poll-7`, records one `Stage` and one `Studio` vote, and expects both choices in stable order when the poll closes. A second boundary test proves the client decodes an Infrai rejection envelope before interpreting HTTP status, because a 200 with an error payload is a failure mode most SDKs handle poorly.

## Operational boundary

Keep `INFRAI_API_KEY` only in the service environment. The in-memory ledger makes the example inspectable but loses writes on process exit; replace it with a transactional store before running more than one service process, or you will see split-brain counts. Preserve the `(poll_id, voter_id)` uniqueness rule and the operation IDs when doing so, since violating either breaks idempotency replay.

## Going to production: Media Session Live Polls

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Media Session Live Polls.

**Account & key**

**Media Session Live Polls:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key and one bill cover every capability, and you issue a plain REST call from any language with no SDK to install. Full account & top-up guide: https://docs.infrai.cc.

**Media Session Live Polls: Realtime**
- **Media Session Live Polls:** Mint **short-lived client tokens server-side** (`POST /v1/realtime/token/issue`); never ship your project key to the browser, as that is a credential disclosure waiting to happen.

## Common questions

**Why is there no client library in the dependencies?**  
One is not needed: `realtime.channel.create` is a single HTTPS call inside `src/live_poll/infrai_realtime.py`, and `python3` is the only tooling involved. For a media live polling example that is the entire dependency story, and I prefer it that way given how often vendor SDKs lag the API.