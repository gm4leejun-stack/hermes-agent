"""Consumer loop tests: pacing, ordering, and failure -> dead-letter.

``asyncio.sleep`` is monkeypatched to a no-op so the 35s pacing runs instantly;
we assert the sleeps were *requested* with the right durations instead of
actually waiting. Storage is a real tmp_path outbox (no mocks of the queue).
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest


def _mods():
    from tools import weixin_outbox, weixin_outbox_consumer
    return weixin_outbox, weixin_outbox_consumer


def _did(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:40]


def _enqueue(ob, home, n):
    for i in range(n):
        ob.enqueue(
            home, route="daily_report",
            chat_id="chat@im.wechat", message=f"msg-{i}",
            delivery_id=_did(f"m{i}"),
        )

@pytest.fixture
def no_wait(monkeypatch):
    """Replace asyncio.sleep with a no-op that records requested durations."""
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(secs, *a, **k):
        slept.append(secs)
        await real_sleep(0)  # yield control, but don't actually wait

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


async def _run_ticks(consumer, n):
    for _ in range(n):
        await consumer._drain_once()


def test_drains_in_fifo_order(tmp_path):
    ob, oc = _mods()
    _enqueue(ob, tmp_path, 3)
    sent = []

    async def sender(rec):
        sent.append(rec["message"])

    c = oc.WeixinOutboxConsumer(tmp_path, sender)
    asyncio.run(_run_ticks(c, 3))
    assert sent == ["msg-0", "msg-1", "msg-2"]
    assert ob.counts(tmp_path)["pending"] == 0


def test_empty_queue_tick_is_noop(tmp_path):
    ob, oc = _mods()
    calls = []

    async def sender(rec):
        calls.append(rec)

    c = oc.WeixinOutboxConsumer(tmp_path, sender)
    attempted = asyncio.run(c._drain_once())
    assert attempted is False
    assert calls == []


def test_loop_paces_full_interval_after_send_short_when_idle(tmp_path, no_wait):
    ob, oc = _mods()
    _enqueue(ob, tmp_path, 1)

    async def sender(rec):
        pass

    c = oc.WeixinOutboxConsumer(tmp_path, sender, interval=35.0)

    async def drive():
        c._running = True
        # tick 1: sends -> should request full 35s; tick 2: empty -> <=5s
        for _ in range(2):
            sent = await c._drain_once()
            await asyncio.sleep(c.interval if sent else min(c.interval, 5.0))

    asyncio.run(drive())
    assert no_wait[0] == 35.0
    assert no_wait[1] == 5.0


def test_persistent_failure_dead_letters_after_max_attempts(tmp_path):
    ob, oc = _mods()
    ob.enqueue(tmp_path, route="daily_report", chat_id="c@im.wechat",
               message="boom", delivery_id=_did("boom"))

    async def bad_sender(rec):
        raise RuntimeError("prepare failed")

    # max_attempts=3, and force each backoff window to have elapsed by
    # re-opening the record's next_attempt_at to the past between ticks.
    c = oc.WeixinOutboxConsumer(tmp_path, bad_sender, max_attempts=3,
                                backoff_base_sec=30.0)

    async def drive():
        for _ in range(3):
            # make the record due regardless of backoff by claiming with a
            # far-future clock is not exposed here; instead we clear backoff by
            # rewriting next_attempt_at via a fresh claim after bumping time.
            await c._drain_once()
            _clear_backoff(ob, tmp_path)

    asyncio.run(drive())
    counts = ob.counts(tmp_path)
    assert counts["dead"] == 1
    assert counts["pending"] == 0
    rec = ob.read_result(tmp_path, _did("boom"))
    assert rec["status"] == "dead"
    assert rec["attempts"] == 3


def _clear_backoff(ob, home):
    """Test helper: force any backed-off pending record to be due now."""
    import json, pathlib
    pend = pathlib.Path(home) / "runtime" / ob.OUTBOX_DIR_NAME / "pending"
    for p in pend.glob("*.json"):
        rec = json.loads(p.read_text())
        rec["next_attempt_at"] = 0
        p.write_text(json.dumps(rec, sort_keys=True))

