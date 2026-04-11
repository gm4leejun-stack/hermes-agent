from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.FEISHU,
        user_id='ou_test',
        chat_id='oc_home',
        user_name='tester',
        chat_type='group',
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id='m1')


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.FEISHU: PlatformConfig(enabled=True, extra={'app_id': 'cli_xxx'})}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._update_prompt_pending = {}
    runner._is_user_authorized = lambda _source: True
    runner._handle_message_with_agent = AsyncMock(
        side_effect=AssertionError('Quant-CC Feishu analysis leaked to the generic agent path')
    )
    return runner


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_short_circuits_agent_and_sends_task_result(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 162})
    poll_task = AsyncMock(
        return_value={
            'id': 162,
            'status': 'succeeded',
            'result': {'message': 'AMZN 建议已推送', 'rec_id': 837},
        }
    )
    wait_event = AsyncMock(return_value={'id': 17, 'payload': {'task_id': 162, 'status': 'succeeded'}})
    ack_event = AsyncMock(return_value=True)
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('请分析一下 AMZN 持仓'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with('oc_home', 'AMZN 建议已推送')
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(162)
    wait_event.assert_awaited_once_with(162)
    ack_event.assert_awaited_once_with(17)


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_failure_returns_programmatic_error_not_freeform(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 163})
    poll_task = AsyncMock(
        return_value={
            'id': 163,
            'status': 'failed',
            'error': 'upstream timeout',
        }
    )
    wait_event = AsyncMock(return_value={'id': 18, 'payload': {'task_id': 163, 'status': 'failed'}})
    ack_event = AsyncMock(return_value=True)
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('帮我看下 AMZN'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with(
        'oc_home',
        'AMZN 分析失败（task_id=163）：upstream timeout',
    )
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(163)
    wait_event.assert_awaited_once_with(163)
    ack_event.assert_awaited_once_with(18)


def test_gateway_run_module_still_exports_delivery_router():
    import gateway.run as gateway_run

    assert gateway_run.DeliveryRouter is not None


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_handles_symbol_adjacent_to_chinese(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 164})
    poll_task = AsyncMock(
        return_value={
            'id': 164,
            'status': 'succeeded',
            'result': {'message': 'AMZN 邻接中文建议已推送', 'rec_id': 838},
        }
    )
    wait_event = AsyncMock(return_value={'id': 19, 'payload': {'task_id': 164, 'status': 'succeeded'}})
    ack_event = AsyncMock(return_value=True)
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with('oc_home', 'AMZN 邻接中文建议已推送')
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(164)
    wait_event.assert_awaited_once_with(164)
    ack_event.assert_awaited_once_with(19)


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_does_not_send_second_error_after_result_already_sent(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 170})
    poll_task = AsyncMock(
        return_value={
            'id': 170,
            'status': 'failed',
            'error': 'analysis_failed',
        }
    )
    wait_event = AsyncMock(side_effect=RuntimeError('quant_cc_http_404:{"detail":"Not Found"}'))
    ack_event = AsyncMock(return_value=True)
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with(
        'oc_home',
        'AMZN 分析失败（task_id=170）：analysis_failed',
    )
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(170)
    wait_event.assert_awaited_once_with(170)
    ack_event.assert_not_awaited()
