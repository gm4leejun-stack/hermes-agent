"""Outbox queue invariants: FIFO, idempotency, backoff, dead-letter — real disk."""
import json
import subprocess
import sys

import pytest


def _mod():
    from tools import weixin_outbox
    return weixin_outbox


def test_enqueue_is_idempotent_and_payload_fenced(tmp_path):
    ob = _mod()
    did = "a" * 32
    first = ob.enqueue(tmp_path, route="daily_report", chat_id="c@im.wechat", message="hi", delivery_id=did)
    assert first["status"] == "queued"
    assert first["attempts"] == 0
    # same id + same payload -> returns existing, no duplicate
    again = ob.enqueue(tmp_path, route="daily_report", chat_id="c@im.wechat", message="hi", delivery_id=did)
    assert again == first
    assert ob.counts(tmp_path)["pending"] == 1
    # same id + different payload -> error, never overwrite
    with pytest.raises(ValueError):
        ob.enqueue(tmp_path, route="daily_report", chat_id="c@im.wechat", message="DIFFERENT", delivery_id=did)


def test_fifo_by_sequence(tmp_path):
    ob = _mod()
    a = ob.enqueue(tmp_path, route="r", chat_id="c", message="first", delivery_id="a" * 32)
    b = ob.enqueue(tmp_path, route="r", chat_id="c", message="second", delivery_id="b" * 32)
    assert a["sequence"] < b["sequence"]
    claimed = ob.claim_next(tmp_path)
    assert claimed["message"] == "first"
    assert claimed["status"] == "sending"
    # oldest is now 'sending', next claim yields the second
    assert ob.claim_next(tmp_path)["message"] == "second"
    # nothing left due
    assert ob.claim_next(tmp_path) is None


def test_success_settles_and_leaves_pending_empty(tmp_path):
    ob = _mod()
    did = "c" * 32
    ob.enqueue(tmp_path, route="r", chat_id="c", message="m", delivery_id=did)
    ob.claim_next(tmp_path)
    rec = ob.mark_result(tmp_path, did, ok=True)
    assert rec["status"] == "settled"
    c = ob.counts(tmp_path)
    assert c["pending"] == 0 and c["settled"] == 1 and c["dead"] == 0
    # idempotent read still finds it (dedup window)
    assert ob.read_result(tmp_path, did)["status"] == "settled"


def test_failure_backs_off_then_dead_letters(tmp_path):
    ob = _mod()
    did = "d" * 32
    ob.enqueue(tmp_path, route="r", chat_id="c", message="m", delivery_id=did)
    now = 1_000_000_000_000
    # attempts 1..2 requeue with growing backoff; attempt 3 (max=3) dead-letters
    ob.claim_next(tmp_path, now_ns=now)
    r1 = ob.mark_result(tmp_path, did, ok=False, error="rate", max_attempts=3, backoff_base_sec=30, now_ns=now)
    assert r1["status"] == "queued" and r1["attempts"] == 1 and r1["next_attempt_at"] > now
    # not due yet -> claim returns None at same now
    assert ob.claim_next(tmp_path, now_ns=now) is None
    later = r1["next_attempt_at"]
    ob.claim_next(tmp_path, now_ns=later)
    r2 = ob.mark_result(tmp_path, did, ok=False, error="rate", max_attempts=3, backoff_base_sec=30, now_ns=later)
    assert r2["status"] == "queued" and r2["attempts"] == 2
    later2 = r2["next_attempt_at"]
    ob.claim_next(tmp_path, now_ns=later2)
    r3 = ob.mark_result(tmp_path, did, ok=False, error="rate", max_attempts=3, backoff_base_sec=30, now_ns=later2)
    assert r3["status"] == "dead" and r3["attempts"] == 3
    c = ob.counts(tmp_path)
    assert c["pending"] == 0 and c["dead"] == 1


def test_single_consumer_under_concurrent_claim(tmp_path):
    ob = _mod()
    ob.enqueue(tmp_path, route="r", chat_id="c", message="only", delivery_id="e" * 32)
    script = (
        "import json,sys; from tools.weixin_outbox import claim_next; "
        "print(json.dumps(claim_next(sys.argv[1])))"
    )
    kids = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True) for _ in range(3)]
    results = []
    for kid in kids:
        out, err = kid.communicate(timeout=30)
        assert kid.returncode == 0, err
        results.append(json.loads(out))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1 and claimed[0]["message"] == "only"
