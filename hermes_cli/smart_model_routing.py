"""Shared smart model routing helpers for CLI and gateway turns."""

from __future__ import annotations

import re
from typing import Any, Dict


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_target(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        "provider": str(raw.get("provider") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
        "base_url": str(raw.get("base_url") or "").strip(),
        "api_key": str(raw.get("api_key") or "").strip(),
    }


def normalize_smart_model_routing(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"enabled": False}
    return {
        "enabled": bool(raw.get("enabled")),
        "max_simple_chars": _coerce_int(raw.get("max_simple_chars"), 160),
        "max_simple_words": _coerce_int(raw.get("max_simple_words"), 28),
        "cheap_model": _normalize_target(raw.get("cheap_model")),
        "complex_model": _normalize_target(raw.get("complex_model")),
    }


def _message_text(user_message: Any) -> str:
    if isinstance(user_message, str):
        return user_message
    if isinstance(user_message, list):
        parts: list[str] = []
        for part in user_message:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)
    if user_message is None:
        return ""
    return str(user_message)


_CODE_MARKERS = (
    "```",
    "def ",
    "class ",
    "function",
    "import ",
    "stack trace",
    "traceback",
    "exception",
    "error:",
    "bug",
    "debug",
    "fix ",
    "refactor",
    "optimize",
    "sql ",
    "regex",
)

_ANALYSIS_MARKERS = (
    "analyze",
    "analysis",
    "compare",
    "tradeoff",
    "architecture",
    "design",
    "reason about",
    "why does",
    "root cause",
    "evaluate",
)

_STRUCTURED_OUTPUT_MARKERS = (
    "json",
    "yaml",
    "schema",
    "csv",
    "markdown table",
    "table with",
    "xml",
)

_MULTISTEP_PATTERNS = (
    r"\bfirst\b.*\bthen\b",
    r"\bstep by step\b",
    r"\bsteps?\b",
    r"\bfinally\b",
)

_TOOL_INTENT_MARKERS = (
    "提醒",
    "定时",
    "创建",
    "发送",
    "安排",
    "计划",
    "记录",
    "查询",
    "删除",
    "修改",
    "schedule",
    "remind",
    "create",
    "send",
    "record",
    "delete",
    "update",
)

_TIME_INTENT_PATTERNS = (
    r"\b\d+\s*(seconds?|minutes?|hours?|days?|weeks?|months?)\s+later\b",
    r"\bin\s+\d+\s*(seconds?|minutes?|hours?|days?|weeks?|months?)\b",
    r"\btonight\b",
    r"\btomorrow\b",
    r"\bnext\s+\w+\b",
    r"\bevery\s+\w+\b",
    r"\d+\s*(秒|分钟|小时|天|周|个月)后",
    r"(今天|今晚|明天|后天|下周|每周|每月|每年)",
)


def _has_complexity_marker(text: str) -> bool:
    lowered = text.lower()
    if "\n\n" in text or text.count("\n") >= 3:
        return True
    if any(marker in lowered for marker in _CODE_MARKERS):
        return True
    if any(marker in lowered for marker in _ANALYSIS_MARKERS):
        return True
    if any(marker in lowered for marker in _STRUCTURED_OUTPUT_MARKERS):
        return True
    return any(re.search(pattern, lowered) for pattern in _MULTISTEP_PATTERNS)


def _has_tool_intent(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _TOOL_INTENT_MARKERS):
        return True
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _TIME_INTENT_PATTERNS)


def is_simple_task(user_message: Any, routing_cfg: Dict[str, Any]) -> bool:
    text = _message_text(user_message).strip()
    chars = len(text)
    words = len(text.split())
    return bool(text) and (
        chars <= int(routing_cfg.get("max_simple_chars") or 160)
        and words <= int(routing_cfg.get("max_simple_words") or 28)
        and not _has_tool_intent(text)
        and not _has_complexity_marker(text)
    )


def resolve_turn_route(
    *,
    user_message: Any,
    primary_model: str,
    primary_runtime: Dict[str, Any],
    routing_cfg: Dict[str, Any] | None,
) -> Dict[str, Any]:
    route = {
        "model": primary_model,
        "runtime": dict(primary_runtime),
    }

    cfg = normalize_smart_model_routing(routing_cfg)
    if not cfg.get("enabled"):
        return route

    target = cfg.get("cheap_model") if is_simple_task(user_message, cfg) else cfg.get("complex_model")
    if not isinstance(target, dict):
        return route

    target_model = str(target.get("model") or "").strip()
    if not target_model:
        return route

    runtime = dict(primary_runtime)
    target_provider = str(target.get("provider") or "").strip()
    target_base_url = str(target.get("base_url") or "").strip()
    target_api_key = str(target.get("api_key") or "").strip()
    runtime_override_requested = any(
        [
            target_provider and target_provider != str(primary_runtime.get("provider") or "").strip(),
            target_base_url and target_base_url != str(primary_runtime.get("base_url") or "").strip(),
            bool(target_api_key),
        ]
    )

    if runtime_override_requested:
        from hermes_cli.runtime_provider import resolve_runtime_provider

        resolved = resolve_runtime_provider(
            requested=target_provider or str(primary_runtime.get("provider") or "").strip() or None,
            explicit_api_key=target_api_key or None,
            explicit_base_url=target_base_url or None,
            target_model=target_model,
        )
        runtime.update(
            {
                "api_key": resolved.get("api_key", runtime.get("api_key")),
                "base_url": resolved.get("base_url", runtime.get("base_url")),
                "provider": resolved.get("provider", runtime.get("provider")),
                "api_mode": resolved.get("api_mode", runtime.get("api_mode")),
                "command": resolved.get("command", runtime.get("command")),
                "args": list(resolved.get("args") or runtime.get("args") or []),
                "credential_pool": resolved.get("credential_pool"),
            }
        )
    else:
        if target_provider:
            runtime["provider"] = target_provider
        if target_base_url:
            runtime["base_url"] = target_base_url
        if target_api_key:
            runtime["api_key"] = target_api_key

    route["model"] = target_model
    route["runtime"] = runtime
    return route
