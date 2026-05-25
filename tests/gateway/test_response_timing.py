from gateway.run import (
    _agent_poll_interval,
    _format_aiohttp_creation_trace,
    _format_gateway_phase_event,
    _format_gateway_phase_trace,
    _mark_gateway_phase,
    _should_wait_for_stream_consumer,
    _start_gateway_phase_trace,
)


def test_gateway_phase_trace_collects_named_steps():
    trace = _start_gateway_phase_trace()

    first = _mark_gateway_phase(trace, "agent_run")
    second = _mark_gateway_phase(trace, "stop_typing")

    assert first >= 0
    assert second >= 0
    assert [phase for phase, _ in trace["phases"]] == [
        "agent_run",
        "stop_typing",
    ]


def test_gateway_phase_trace_formats_compact_breakdown():
    trace = {"phases": [("agent_run", 4123.4), ("stop_typing", 12.34)]}

    text = _format_gateway_phase_trace(trace)

    assert "agent_run=4123.4ms" in text
    assert "stop_typing=12.3ms" in text


def test_gateway_phase_event_formats_label_fields_and_breakdown():
    trace = {"phases": [("run_conversation", 4288.2), ("maybe_auto_title", 1.9)]}

    text = _format_gateway_phase_event(
        "agent internal timing breakdown",
        trace,
        session="sess-123",
        model="deepseek/deepseek-v4-flash",
    )

    assert text.startswith("agent internal timing breakdown:")
    assert "session=sess-123" in text
    assert "model=deepseek/deepseek-v4-flash" in text
    assert "run_conversation=4288.2ms" in text
    assert "maybe_auto_title=1.9ms" in text


def test_agent_poll_interval_defaults_to_subsecond(monkeypatch):
    monkeypatch.delenv("HERMES_AGENT_POLL_INTERVAL", raising=False)

    interval = _agent_poll_interval()

    assert interval == 0.25


def test_agent_poll_interval_rejects_non_positive_values(monkeypatch):
    monkeypatch.setenv("HERMES_AGENT_POLL_INTERVAL", "0")

    interval = _agent_poll_interval()

    assert interval == 0.25


def test_stream_consumer_wait_skipped_when_consumer_never_created():
    assert _should_wait_for_stream_consumer([None]) is False


def test_stream_consumer_wait_used_when_consumer_exists():
    assert _should_wait_for_stream_consumer(["consumer"]) is True


def test_aiohttp_creation_trace_keeps_tail_frames():
    trace = [
        ("irrelevant.py", 1, "ignored", "x"),
        ("gateway/run.py", 100, "_open_connection", "self._session = aiohttp.ClientSession()"),
        ("agent/title_generator.py", 42, "generate_title", "response = call_llm(...)"),
    ]

    text = _format_aiohttp_creation_trace(trace)

    assert "gateway/run.py:100 in _open_connection" in text
    assert "agent/title_generator.py:42 in generate_title" in text
    assert "ignored" not in text
