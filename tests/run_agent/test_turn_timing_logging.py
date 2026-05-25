import logging
from unittest.mock import MagicMock

import pytest

from run_agent import AIAgent


def _bare_agent():
    agent = AIAgent.__new__(AIAgent)
    agent.session_id = "test-session"
    return agent


def test_timed_turn_phase_logs_elapsed_ms(caplog):
    agent = _bare_agent()

    with caplog.at_level(logging.INFO, logger="run_agent"):
        result = agent._timed_turn_phase("persist_session", lambda: "ok")

    assert result == "ok"
    assert any(
        "turn phase:" in record.message
        and "phase=persist_session" in record.message
        and "elapsed_ms=" in record.message
        for record in caplog.records
    )


def test_timed_turn_phase_logs_failure_and_reraises(caplog):
    agent = _bare_agent()

    def boom():
        raise RuntimeError("kaput")

    with caplog.at_level(logging.WARNING, logger="run_agent"):
        with pytest.raises(RuntimeError, match="kaput"):
            agent._timed_turn_phase("hook.post_llm_call", boom)

    assert any(
        "turn phase failed:" in record.message
        and "phase=hook.post_llm_call" in record.message
        and "elapsed_ms=" in record.message
        and "kaput" in record.message
        for record in caplog.records
    )


def test_sync_external_memory_logs_subphase_timings(caplog):
    agent = _bare_agent()
    agent._memory_manager = MagicMock()

    with caplog.at_level(logging.INFO, logger="run_agent"):
        agent._sync_external_memory_for_turn(
            original_user_message="hi",
            final_response="hey",
            interrupted=False,
        )

    messages = [record.message for record in caplog.records]
    assert any("phase=memory.sync_all" in msg for msg in messages)
    assert any("phase=memory.queue_prefetch_all" in msg for msg in messages)
