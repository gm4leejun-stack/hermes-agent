"""Step 4 Task A: deliver_only for weixin enqueues (202) instead of sync-send (200/502).

Other targets (telegram/wecom/github_comment) keep the original synchronous path.
WebhookPlatform is constructed via __new__ to skip its heavy __init__; only the
two collaborators _handle_deliver_only touches are stubbed.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path


def _platform(tmp_home, monkeypatch):
    from gateway.platforms import webhook as wh
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: Path(tmp_home))
    p = wh.WebhookAdapter.__new__(wh.WebhookAdapter)  # skip heavy __init__
    p._render_delivery_extra = lambda extra, payload: {"chat_id": "o9_x@im.wechat"}
    return p, wh


def test_weixin_route_enqueues_and_returns_202(tmp_path, monkeypatch):
    p, wh = _platform(tmp_path, monkeypatch)
    rc = {"deliver": "weixin", "deliver_extra": {}}
    resp = asyncio.run(
        p._handle_deliver_only("REPORT BODY", {}, rc, "daily_report", "evt", "ignored-id", None)
    )
    assert resp.status == 202
    from tools import weixin_outbox
    did = hashlib.sha256("daily_report\x00o9_x@im.wechat\x00REPORT BODY".encode()).hexdigest()[:40]
    rec = weixin_outbox.read_result(tmp_path, did)
    assert rec is not None and rec["status"] == "queued" and rec["message"] == "REPORT BODY"


def test_non_weixin_route_still_synchronous(tmp_path, monkeypatch):
    p, wh = _platform(tmp_path, monkeypatch)
    called = {}

    async def fake_direct(prompt, delivery):
        called["hit"] = True
        return wh.SendResult(success=True)

    p._direct_deliver = fake_direct
    rc = {"deliver": "telegram", "deliver_extra": {}}
    resp = asyncio.run(p._handle_deliver_only("hi", {}, rc, "r", "evt", "id", None))
    assert called.get("hit") is True and resp.status == 200
