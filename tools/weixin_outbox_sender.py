"""Step 3: the REAL WeChat sender for the outbox consumer.

This is the bridge between the durable outbox (tools/weixin_outbox.py) and the
gateway's existing WeChat send path. It adds NOTHING new to how a message
actually reaches WeChat — it just calls the same code the live webhook already
uses:

    WebhookPlatform._deliver_cross_platform("weixin", message, delivery)
        -> _find_adapter(Platform.WEIXIN, profile).send(chat_id, message)
        -> SendResult(success=..., error=...)

The consumer's contract is simple: a ``sender(record)`` coroutine returns None
on success and RAISES on failure (the raise is the only failure signal, which
triggers backoff / dead-lettering). ``_deliver_cross_platform`` never raises —
it returns ``SendResult(success=False, ...)`` — so this wrapper translates an
unsuccessful result into an exception.

Nothing imports this module yet; wiring it into a running consumer is a
separate step. Building it here is a pure addition with zero live impact.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("hermes.weixin_outbox")

Sender = Callable[[dict], Awaitable[None]]

class WeixinSendError(RuntimeError):
    """Raised when the gateway send path reports failure (so the consumer backs off)."""


def make_webhook_sender(webhook_platform: Any, *, profile: Optional[str] = None) -> Sender:
    """Build a ``sender(record)`` bound to a live WebhookPlatform instance.

    The returned coroutine reuses ``_deliver_cross_platform`` unchanged, so a
    message from the outbox travels the exact same route as a message the live
    webhook delivers today. It succeeds silently or raises WeixinSendError.

    ``record`` is an outbox record: it must carry ``chat_id`` and ``message``
    (see tools/weixin_outbox.enqueue). ``profile`` binds the send to a gateway
    profile scope; None means the default profile.
    """

    async def _send(record: dict) -> None:
        chat_id = record.get("chat_id") or ""
        message = record.get("message")
        delivery_id = record.get("delivery_id") or record.get("id") or "?"
        if not chat_id or not isinstance(message, str):
            # A malformed record can never succeed; raising sends it down the
            # normal failure path (backoff, then dead-letter) rather than
            # silently dropping it.
            raise WeixinSendError(f"record {delivery_id} missing chat_id or message")
        # `delivery` mirrors the shape _deliver_cross_platform reads: it pulls
        # chat_id from deliver_extra and the profile scope from `profile`.
        delivery = {"profile": profile, "deliver_extra": {"chat_id": chat_id}}
        result = await webhook_platform._deliver_cross_platform("weixin", message, delivery)
        if result is None or not getattr(result, "success", False):
            err = getattr(result, "error", "") or "send reported failure"
            logger.warning("[weixin-outbox] send failed id=%s: %s", delivery_id, err)
            raise WeixinSendError(err)
        logger.info("[weixin-outbox] delivered id=%s chat=%s bytes=%d",
                    delivery_id, chat_id, len(message.encode("utf-8")))

    return _send

