"""Event bus helpers on Redis Streams.

Why Streams (not a plain list)? A list item is delivered to ONE consumer. We need the same event to reach
notification, ledger AND audit. Each service reads the stream through its own *consumer group*, so every
group gets every event. Delivery is at-least-once, so consumers MUST ignore duplicates (use event_id).
"""
import asyncio
import json
import logging
import os
import time
import uuid

import redis

STREAM = os.environ.get("EVENT_STREAM", "northbank.events")
log = logging.getLogger("events")


def make_event(event_type: str, user_id, **data) -> dict:
    return {"event_id": str(uuid.uuid4()), "type": event_type, "occurred_at": int(time.time()),
            "user_id": user_id, **data}


def publish(client, event: dict) -> bool:
    """Best effort: a bus outage must never fail a business operation that already succeeded."""
    try:
        if client is None:
            log.info("no REDIS_URL set, event %s not published", event.get("type"))
            return False
        client.xadd(STREAM, {"data": json.dumps(event)}, maxlen=100_000, approximate=True)
        return True
    except Exception as exc:
        log.error("could not publish event %s: %s", event.get("type"), exc)
        return False


def ensure_group(client, group: str) -> None:
    try:
        client.xgroup_create(STREAM, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def consume_once(client, group: str, consumer: str, handler, block_ms: int = 1000, count: int = 10) -> int:
    """Read up to `count` new events for this group, call handler(event) for each, then ack.
    A handler error is logged and the event is acked anyway (a 'poison' event must not block the queue).
    Production teams send these to a dead-letter stream instead; that is a Phase 11 exercise."""
    response = client.xreadgroup(group, consumer, {STREAM: ">"}, count=count, block=block_ms)
    handled = 0
    for _stream, messages in response or []:
        for msg_id, fields in messages:
            try:
                handler(json.loads(fields["data"]))
            except Exception as exc:
                log.error("dropping bad event %s: %s", msg_id, exc)
            client.xack(STREAM, group, msg_id)
            handled += 1
    return handled


async def worker_loop(get_client, group: str, handler):
    """Background consumer started from a service's lifespan. Reconnects if Redis is down."""
    consumer = f"{group}-{os.getpid()}"
    while True:
        try:
            client = get_client()
            if client is None:
                log.info("no REDIS_URL set, consumer %s not started", group)
                return
            ensure_group(client, group)
            log.info("consumer %s listening on %s", group, STREAM)
            while True:
                await asyncio.to_thread(consume_once, client, group, consumer, handler)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("consumer %s error (retrying in 2s): %s", group, exc)
            await asyncio.sleep(2)
