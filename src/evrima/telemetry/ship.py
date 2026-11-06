"""Shipping the buffer to the collector: `flask evrima telemetry ship`, run every minute.

Outside requests, so a slow or unreachable collector never slows down the
website. How a batch travels (reviewed 2026-11-06):

1. The oldest events are moved atomically from the buffer to an "in flight"
   list, together with a new batch id. While they are in flight, new events
   pushed to a full buffer trim only the buffer, so they can never push out
   events that are being sent (they used to be deleted by count afterwards,
   which dropped unsent events).
2. The batch is posted. Only when the collector has accepted it (or called it
   invalid) is the in-flight list deleted. A batch that failed stays in flight
   and the next run sends it again with the same id, so the collector can drop
   a batch it had already stored but whose answer was lost.
3. One shipper at a time: a lock in Redis keeps a cron job and a sidecar (or two
   replicas) from sending the same events under two ids.

Redirects are never followed: the batch carries the website's token, and a
redirect could take it to another host or to plain HTTP.
"""

import gzip
import http.client
import json
import urllib.error
import urllib.request
import uuid

import redis
from flask import current_app

from evrima import redis_client, telemetry
from evrima.version import get_version

BATCH_SIZE = 1000
TIMEOUT_SECONDS = 10

INFLIGHT_KEY = "evrima:telemetry:inflight"
INFLIGHT_BATCH_KEY = "evrima:telemetry:inflight:batch"
LOCK_KEY = "evrima:telemetry:ship"
# Longer than one batch can take (a timeout of 10 s); refreshed after every batch.
LOCK_SECONDS = 120
_LOCAL_INFLIGHT = "evrima.telemetry.inflight"


class ShipError(RuntimeError):
    """The collector could not take the batch now; it stays and is sent again later."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so a 3xx comes back as an HTTPError with its status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _text(item) -> str:
    return item.decode() if isinstance(item, bytes) else item


def _take(count: int) -> tuple[str, list[str]] | None:
    """The batch to send: the one still in flight, or up to `count` oldest events moved into flight."""
    client = redis_client.get_client()
    if client is None:
        store = current_app.extensions
        if store.get(_LOCAL_INFLIGHT) is None:
            buffer = store.get(telemetry._LOCAL_KEY, [])
            if not buffer:
                return None
            store[_LOCAL_INFLIGHT] = (str(uuid.uuid4()), buffer[:count])
            del buffer[:count]
        return store[_LOCAL_INFLIGHT]

    events = [_text(item) for item in client.lrange(INFLIGHT_KEY, 0, -1)]
    if events:
        batch = client.get(INFLIGHT_BATCH_KEY)
        if batch is None:
            batch = str(uuid.uuid4())
            client.set(INFLIGHT_BATCH_KEY, batch)
        return _text(batch), events
    waiting = min(count, client.llen(telemetry.BUFFER_KEY))
    if not waiting:
        return None
    batch = str(uuid.uuid4())
    # MULTI/EXEC: the move and the batch id happen together or not at all.
    with client.pipeline(transaction=True) as pipe:
        for _ in range(waiting):
            pipe.lmove(telemetry.BUFFER_KEY, INFLIGHT_KEY, "LEFT", "RIGHT")
        pipe.set(INFLIGHT_BATCH_KEY, batch)
        moved = [_text(item) for item in pipe.execute()[:-1] if item is not None]
    if not moved:
        client.delete(INFLIGHT_BATCH_KEY)
        return None
    return batch, moved


def _done() -> None:
    """Forget the batch in flight (the collector took it, or it can never take it)."""
    client = redis_client.get_client()
    if client is None:
        current_app.extensions.pop(_LOCAL_INFLIGHT, None)
    else:
        client.delete(INFLIGHT_KEY, INFLIGHT_BATCH_KEY)


def _lock() -> str | None:
    """Take the shipping lock; return its token, or None when another shipper holds it."""
    client = redis_client.get_client()
    if client is None:
        return "local"                 # the in-process buffer belongs to this process alone
    token = uuid.uuid4().hex
    return token if client.set(LOCK_KEY, token, nx=True, ex=LOCK_SECONDS) else None


def _refresh_lock() -> None:
    client = redis_client.get_client()
    if client is not None:
        client.expire(LOCK_KEY, LOCK_SECONDS)


def _unlock(token: str) -> None:
    """Release the lock if it is still ours (it may have expired and been taken)."""
    client = redis_client.get_client()
    if client is not None and _text(client.get(LOCK_KEY) or b"") == token:
        client.delete(LOCK_KEY)


def payload(batch: str, events: list[str]) -> bytes:
    """The batch as the protocol describes it, gzip-compressed."""
    body = {
        "v": 1,
        "batch": batch,
        "sent_at": telemetry.now_iso(),
        "versions": {"evrima": get_version(), "website": current_app.import_name},
        "events": [json.loads(item) for item in events],
    }
    return gzip.compress(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())


def post(data: bytes) -> int:
    """Send one batch; return the collector's HTTP status (0 when it could not be reached)."""
    config = current_app.config
    req = urllib.request.Request(
        f"{config['TELEMETRY_ENDPOINT']}/v1/ingest", data=data, method="POST",
        headers={"Authorization": f"Bearer {config['TELEMETRY_TOKEN']}",
                 "Content-Type": "application/json", "Content-Encoding": "gzip"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        # Unreachable, timed out, or an answer that is not HTTP.
        return 0


def ship() -> int:
    """Send the whole buffer in batches; return how many events the collector took.

    Raises ShipError when the collector refuses for a reason that a later run
    may not have (unreachable, redirect, 401, 429, 5xx) or Redis is down; the
    batch then stays in flight and is sent again.
    """
    if not telemetry.enabled():
        return 0
    try:
        token = _lock()
    except redis.RedisError as error:
        raise ShipError(f"Redis is unreachable ({type(error).__name__}).") from error
    if token is None:
        current_app.logger.info("Telemetry is being shipped by another process; skipped.")
        return 0
    sent = 0
    try:
        while (batch := _take(BATCH_SIZE)) is not None:
            batch_id, events = batch
            status = post(payload(batch_id, events))
            if status in (200, 202):
                sent += len(events)
            elif status in (400, 413):
                # The batch itself is wrong; sending it again cannot help and
                # would block everything behind it.
                current_app.logger.error("Telemetry batch of %d events refused (%d), dropped.",
                                         len(events), status)
            else:
                raise ShipError(f"The collector did not take the batch (status {status or 'unreachable'}); "
                                "it will be sent again.")
            _done()
            _refresh_lock()
    except redis.RedisError as error:
        raise ShipError(f"Redis is unreachable ({type(error).__name__}).") from error
    finally:
        try:
            _unlock(token)
        except redis.RedisError:
            pass                       # the lock expires on its own
    return sent
