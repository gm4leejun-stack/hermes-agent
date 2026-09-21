"""Step 3 tests: the real-send wrapper reuses _deliver_cross_platform and
translates its SendResult into the consumer's raise-on-failure contract.

No real WeChat: a FakeWebhook stands in for WebhookPlatform, recording the
exact ("weixin", message, delivery) it was called with.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass


def _mods():
    from tools import weixin_outbox, weixin_outbox_sender
    return weixin_outbox, weixin_outbox_sender


@dataclass
class FakeResult:
    success: bool
    error: str = ""


class FakeWebhook:
    """Stand-in for WebhookPlatform: records calls, returns a scripted result."""

    def __init__(self, result: FakeResult):
        self._result = result
        self.calls: list[tuple] = []

    async def _deliver_cross_platform(self, platform_name, content, delivery):
        self.calls.append((platform_name, content, delivery))
        return self._result


def _did(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:40]


def test_success_calls_deliver_and_does_not_raise():
    _, sender_mod = _mods()
    fake = FakeWebhook(FakeResult(success=True))
    send = sender_mod.make_webhook_sender(fake, profile=None)
    record = {"delivery_id": _did("a"), "chat_id": "chat@im.wechat", "message": "hello"}

    asyncio.run(send(record))

    assert len(fake.calls) == 1
    platform, content, delivery = fake.calls[0]
    assert platform == "weixin"
    assert content == "hello"
    assert delivery["deliver_extra"]["chat_id"] == "chat@im.wechat"
    assert delivery["profile"] is None


def test_failed_result_raises_send_error():
    _, sender_mod = _mods()
    fake = FakeWebhook(FakeResult(success=False, error="prepare failed"))
    send = sender_mod.make_webhook_sender(fake)
    record = {"delivery_id": _did("b"), "chat_id": "chat@im.wechat", "message": "hi"}

    try:
        asyncio.run(send(record))
        assert False, "expected WeixinSendError"
    except sender_mod.WeixinSendError as exc:
        assert "prepare failed" in str(exc)


def test_malformed_record_raises_without_calling_deliver():
    _, sender_mod = _mods()
    fake = FakeWebhook(FakeResult(success=True))
    send = sender_mod.make_webhook_sender(fake)

    try:
        asyncio.run(send({"delivery_id": _did("c"), "message": "no chat"}))
        assert False, "expected WeixinSendError"
    except sender_mod.WeixinSendError:
        pass
    assert fake.calls == []


def test_end_to_end_consumer_drains_via_real_wrapper(tmp_path):
    """Enqueue -> consumer -> wrapper -> FakeWebhook, proving the pieces compose."""
    ob, sender_mod = _mods()
    from tools import weixin_outbox_consumer

    home = tmp_path
    ob.enqueue(home, route="daily_report", chat_id="chat@im.wechat",
               message="report body", delivery_id=_did("e2e"))

    fake = FakeWebhook(FakeResult(success=True))
    send = sender_mod.make_webhook_sender(fake)
    consumer = weixin_outbox_consumer.WeixinOutboxConsumer(home, send)

    drained = asyncio.run(consumer._drain_once())

    assert drained is True
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == "report body"
    assert ob.counts(home)["pending"] == 0
    assert ob.read_result(home, _did("e2e"))["status"] == "settled"

