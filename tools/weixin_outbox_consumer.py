"""Single in-gateway consumer that drains the WeChat outbox at a fixed pace.

The consumer is deliberately dumb: it claims the oldest due record, hands it to
an injected ``sender`` coroutine, records the result, then sleeps ``interval``
seconds before looking again. WeChat's relay hard-limits us to ~1 msg / 30s, so
``interval`` defaults to 35s to stay comfortably under that ceiling.

``sender`` contract:
    async def sender(record: dict) -> None
        # send record["message"] to record["chat_id"]; raise on failure.

The sender raising is the ONLY failure signal — the consumer never inspects the
exception type, it just calls ``mark_result(ok=False, error=...)`` which applies
backoff or dead-letters at ``max_attempts``. This keeps the pacing loop free of
any WeChat-specific knowledge and makes the dry-run stub a one-liner.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from . import weixin_outbox

logger = logging.getLogger("hermes.weixin_outbox")

Sender = Callable[[dict], Awaitable[None]]

class WeixinOutboxConsumer:
    """Owns one drain loop. Not safe to run two against the same profile — the
    outbox lock allows only one claimer at a time, but running two loops wastes a
    task and muddies logs, so the gateway starts exactly one."""

    def __init__(
        self,
        profile_home,
        sender: Sender,
        *,
        interval: float = 35.0,
        max_attempts: int = 6,
        backoff_base_sec: float = 30.0,
        backoff_cap_sec: float = 300.0,
    ) -> None:
        self.profile_home = profile_home
        self.sender = sender
        self.interval = float(interval)
        self.max_attempts = int(max_attempts)
        self.backoff_base_sec = float(backoff_base_sec)
        self.backoff_cap_sec = float(backoff_cap_sec)
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="weixin-outbox-drain")
        logger.info("weixin outbox consumer started (interval=%.0fs)", self.interval)

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown best-effort
            pass
        logger.info("weixin outbox consumer stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                sent = await self._drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a crashing tick must not kill the loop
                logger.exception("weixin outbox: drain tick crashed")
                sent = False
            # Only pace after an actual send attempt; an empty queue should not
            # block for 35s, but we still sleep a short beat to avoid a hot spin.
            await asyncio.sleep(self.interval if sent else min(self.interval, 5.0))

    async def _drain_once(self) -> bool:
        """Claim + deliver at most one record. Returns True if a record was
        attempted (so the caller applies the full pacing interval)."""
        record = weixin_outbox.claim_next(self.profile_home)
        if record is None:
            return False
        delivery_id = record["delivery_id"]
        try:
            await self.sender(record)
        except asyncio.CancelledError:
            # Shutdown mid-send: leave it 'sending'; claim_next re-picks stale
            # 'sending' rows on next boot is NOT implemented yet — see note below.
            raise
        except Exception as exc:  # noqa: BLE001 - any failure -> backoff/dead-letter
            weixin_outbox.mark_result(
                self.profile_home, delivery_id,
                ok=False, error=repr(exc),
                max_attempts=self.max_attempts,
                backoff_base_sec=self.backoff_base_sec,
                backoff_cap_sec=self.backoff_cap_sec,
            )
            logger.warning("weixin outbox: send failed id=%s: %r", delivery_id, exc)
            return True
        weixin_outbox.mark_result(
            self.profile_home, delivery_id, ok=True,
            max_attempts=self.max_attempts,
        )
        logger.info("weixin outbox: sent id=%s route=%s", delivery_id, record.get("route"))
        return True


async def dry_run_sender(record: dict) -> None:
    """Step-2 stub: pretends to send. Logs what WOULD go out, never touches
    WeChat. Swap for the real client in Step 3."""
    logger.info(
        "[DRY-RUN] would send id=%s route=%s chat=%s bytes=%d",
        record.get("delivery_id"), record.get("route"),
        record.get("chat_id"), len(record.get("message", "")),
    )


def _mono_ns() -> int:
    return time.time_ns()

