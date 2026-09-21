"""Durable, paced outbox for weixin (iLink) delivery.

Producers enqueue and return immediately; a single in-gateway consumer drains
the queue at a weixin-safe pace (~1 msg / 30s hard limit), with exponential
backoff and a dead-letter sink. Pure-file storage (one JSON per message under a
process-shared lock) — deliberately avoids SQLite. Mirrors the locking and
monotonic-sequence discipline of tools/bot_live_delivery.py.

State machine per message: queued -> sending -> (settled | queued+backoff | dead).
Wall time can roll back, so FIFO order uses a lock-allocated monotonic sequence.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from utils import atomic_json_write, fsync_directory
from hermes_cli.active_sessions import _FileLock

OUTBOX_DIR_NAME = "weixin_outbox"
_PENDING = "pending"
_DEAD = "dead"
_SETTLED = "settled"
_ACTIVE = frozenset({"queued", "sending"})


def _delivery_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32,64}", value) is None:
        raise ValueError("delivery id must be 32 to 64 lowercase hex characters")
    return value


def _root(home: Path | str) -> Path:
    return Path(home).resolve() / "runtime" / OUTBOX_DIR_NAME


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _write(path: Path, record: dict[str, Any]) -> None:
    atomic_json_write(path, record, indent=None, sort_keys=True, fsync_dir=True, mode=0o600)


@contextmanager
def _locked(home: Path | str):
    root = _root(home)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    for name in (_PENDING, _DEAD, _SETTLED):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    fsync_directory(root.parent)
    lock = root / ".lock"
    fd = os.open(lock, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    with _FileLock(lock):
        yield root


def _find_existing(root: Path, key: str) -> tuple[Path, dict[str, Any]] | None:
    """Locate an already-enqueued/terminal record by id across all sub-dirs (idempotency)."""
    for name in (_PENDING, _DEAD, _SETTLED):
        path = root / name / f"{key}.json"
        record = _read(path)
        if record is not None:
            return path, record
    return None


def _next_sequence(root: Path) -> int:
    """Monotonic high-water mark allocated while holding the lock (clock-rollback safe)."""
    seqs = []
    for name in (_PENDING, _DEAD, _SETTLED):
        for candidate in (root / name).glob("*.json"):
            record = _read(candidate)
            if record is not None:
                seqs.append(record.get("sequence", 0))
    return (max(seqs) if seqs else 0) + 1


def enqueue(
    profile_home: Path | str, *, route: str, chat_id: str, message: str,
    delivery_id: str | None = None,
) -> dict[str, Any]:
    """Admit a message durably and return immediately. Idempotent on delivery_id.

    Re-enqueue with the same id returns the existing record (no duplicate send).
    Reusing an id with a different (route, chat_id, message) is an error.
    """
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    if not (isinstance(route, str) and route) or not (isinstance(chat_id, str) and chat_id):
        raise ValueError("route and chat_id are required non-empty strings")
    key = _delivery_id(delivery_id if delivery_id is not None else uuid.uuid4().hex)
    with _locked(profile_home) as root:
        found = _find_existing(root, key)
        if found is not None:
            _, existing = found
            if (existing["route"], existing["chat_id"], existing["message"]) != (route, chat_id, message):
                raise ValueError("delivery id already belongs to a different payload")
            return existing
        record = dict(
            id=key, delivery_id=key, sequence=_next_sequence(root),
            route=route, chat_id=chat_id, message=message,
            status="queued", created_at=time.time_ns(),
            attempts=0, next_attempt_at=0, last_error="",
        )
        _write(root / _PENDING / f"{key}.json", record)
        return record


def claim_next(profile_home: Path | str, *, now_ns: int | None = None) -> dict[str, Any] | None:
    """Claim the oldest due message (queued, next_attempt_at<=now). Marks it 'sending'.

    Single-consumer by design; the lock still guards against a second drainer.
    Returns None when nothing is due. Send happens OUTSIDE the lock (see drainer).
    """
    now = now_ns if now_ns is not None else time.time_ns()
    if not (_root(profile_home) / _PENDING).is_dir():
        return None
    with _locked(profile_home) as root:
        due = []
        for path in (root / _PENDING).glob("*.json"):
            record = _read(path)
            if record is not None and record["status"] == "queued" and record.get("next_attempt_at", 0) <= now:
                due.append(record)
        if not due:
            return None
        record = min(due, key=lambda r: (r.get("sequence", r["created_at"]), r["delivery_id"]))
        record.update(status="sending", claimed_at=now)
        _write(root / _PENDING / f"{record['delivery_id']}.json", record)
        return record


def _backoff_ns(attempts: int, base_sec: float, cap_sec: float) -> int:
    delay = min(cap_sec, base_sec * (2 ** max(0, attempts - 1)))
    return int(delay * 1_000_000_000)


def mark_result(
    profile_home: Path | str, delivery_id: str, *, ok: bool, error: str = "",
    max_attempts: int = 6, backoff_base_sec: float = 30.0, backoff_cap_sec: float = 300.0,
    now_ns: int | None = None,
) -> dict[str, Any]:
    """Record a send outcome. Success -> settled/. Failure -> requeue w/ backoff, or dead/ at cap."""
    key = _delivery_id(delivery_id)
    now = now_ns if now_ns is not None else time.time_ns()
    with _locked(profile_home) as root:
        path = root / _PENDING / f"{key}.json"
        record = _read(path)
        if record is None:
            raise FileNotFoundError(f"outbox message not found in pending: {key}")
        if record["status"] != "sending":
            raise ValueError("message must be claimed (sending) before recording a result")
        record["attempts"] = record.get("attempts", 0) + 1
        if ok:
            record.update(status="settled", settled_at=now, last_error="")
            _write(root / _SETTLED / f"{key}.json", record)
            os.unlink(path)
            return record
        record["last_error"] = error
        if record["attempts"] >= max_attempts:
            record.update(status="dead", dead_at=now)
            _write(root / _DEAD / f"{key}.json", record)
            os.unlink(path)
            return record
        record.update(status="queued", next_attempt_at=now + _backoff_ns(record["attempts"], backoff_base_sec, backoff_cap_sec))
        _write(path, record)
        return record


def read_result(profile_home: Path | str, delivery_id: str) -> dict[str, Any] | None:
    """Read a message's current record from whichever sub-dir holds it, without mutating."""
    with _locked(profile_home) as root:
        found = _find_existing(root, _delivery_id(delivery_id))
        return found[1] if found is not None else None


def counts(profile_home: Path | str) -> dict[str, int]:
    """Depth of each sub-dir — used by the healthcheck for backlog/dead-letter alerts."""
    root = _root(profile_home)
    return {name: len(list((root / name).glob("*.json"))) if (root / name).is_dir() else 0
            for name in (_PENDING, _DEAD, _SETTLED)}
