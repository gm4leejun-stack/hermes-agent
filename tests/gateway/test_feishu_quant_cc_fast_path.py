from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.platforms.base import SendResult
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
    fetch_detail = AsyncMock(return_value='🔍 AMZN 决策依据 #837\n详细报告正文')
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('请分析一下 AMZN 持仓'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with('oc_home', '🔍 AMZN 决策依据 #837\n详细报告正文')
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(162)
    fetch_detail.assert_awaited_once_with(837)
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
    fetch_detail = AsyncMock(return_value=None)
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with('oc_home', 'AMZN 邻接中文建议已推送')
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(164)
    fetch_detail.assert_awaited_once_with(838)
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


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_sends_followup_result_after_submit_message_when_task_not_terminal(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 177})
    poll_task = AsyncMock(return_value=None)
    wait_event = AsyncMock(
        return_value={
            'id': 27,
            'payload': {
                'task_id': 177,
                'status': 'succeeded',
                'result_json': '{"message": "AMZN 建议已推送", "rec_id": 847}',
            },
        }
    )
    ack_event = AsyncMock(return_value=True)
    fetch_detail = AsyncMock(return_value='🔍 AMZN 决策依据 #847\n完整分析报告')
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    assert runner.adapters[Platform.FEISHU].send.await_args_list == [
        (( 'oc_home', 'AMZN 分析任务已提交（task_id=177），结果仍在生成中，请稍后查看。'),),
        (( 'oc_home', '🔍 AMZN 决策依据 #847\n完整分析报告'),),
    ]
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(177)
    fetch_detail.assert_awaited_once_with(847)
    wait_event.assert_awaited_once_with(177)
    ack_event.assert_awaited_once_with(27)


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_refetches_task_result_when_engine_event_lacks_payload(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 178})
    poll_task = AsyncMock(return_value=None)
    fetch_task = AsyncMock(
        return_value={
            'id': 178,
            'status': 'succeeded',
            'result': {'message': 'AMZN 最终分析已推送', 'rec_id': 848},
        }
    )
    wait_event = AsyncMock(
        return_value={
            'id': 28,
            'payload': {
                'task_id': 178,
                'status': 'succeeded',
            },
        }
    )
    ack_event = AsyncMock(return_value=True)
    fetch_detail = AsyncMock(return_value='🔍 AMZN 决策依据 #848\n最终详细报告')
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_task', fetch_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    assert runner.adapters[Platform.FEISHU].send.await_args_list == [
        (('oc_home', 'AMZN 分析任务已提交（task_id=178），结果仍在生成中，请稍后查看。'),),
        (('oc_home', '🔍 AMZN 决策依据 #848\n最终详细报告'),),
    ]
    submit.assert_awaited_once()
    poll_task.assert_awaited_once_with(178)
    fetch_task.assert_awaited_once_with(178)
    fetch_detail.assert_awaited_once_with(848)
    wait_event.assert_awaited_once_with(178)
    ack_event.assert_awaited_once_with(28)


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_logs_followup_send_failure_when_adapter_returns_unsuccessful_result(
    monkeypatch, caplog
):
    import gateway.run as gateway_run

    runner = _make_runner()
    runner.adapters[Platform.FEISHU].send = AsyncMock(
        side_effect=[
            SendResult(success=True, message_id='msg_submit'),
            SendResult(success=False, error='[230099] send denied'),
        ]
    )
    submit = AsyncMock(return_value={'task_id': 179})
    poll_task = AsyncMock(return_value=None)
    wait_event = AsyncMock(
        return_value={
            'id': 29,
            'payload': {
                'task_id': 179,
                'status': 'succeeded',
                'result_json': '{"message": "AMZN 建议已推送", "rec_id": 849}',
            },
        }
    )
    ack_event = AsyncMock(return_value=True)
    fetch_detail = AsyncMock(return_value='🔍 <b>AMZN 决策依据 #849</b>\n详细报告')
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    with caplog.at_level("WARNING"):
        result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    assert runner.adapters[Platform.FEISHU].send.await_args_list == [
        (('oc_home', 'AMZN 分析任务已提交（task_id=179），结果仍在生成中，请稍后查看。'),),
        (('oc_home', '🔍 <b>AMZN 决策依据 #849</b>\n详细报告'),),
    ]
    assert "Feishu Quant-CC engine event follow-up failed: feishu_send_failed:[230099] send denied" in caplog.text
    fetch_detail.assert_awaited_once_with(849)
    ack_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_feishu_quant_cc_analysis_sends_layer1_and_layer2_reports_when_task_exposes_both_ids(monkeypatch):
    import gateway.run as gateway_run

    runner = _make_runner()
    submit = AsyncMock(return_value={'task_id': 180})
    poll_task = AsyncMock(
        return_value={
            'id': 180,
            'status': 'succeeded',
            'result': {
                'message': 'AMZN 建议已推送',
                'rec_id': 853,
                'layer1_id': 853,
                'layer2_id': 854,
            },
        }
    )
    wait_event = AsyncMock(return_value={'id': 30, 'payload': {'task_id': 180, 'status': 'succeeded'}})
    ack_event = AsyncMock(return_value=True)
    fetch_detail = AsyncMock(
        side_effect=[
            '🔍 <b>AMZN 决策依据 #853</b>\n固定策略报告',
            '🔍 <b>AMZN 决策依据 #854</b>\nLLM策略报告',
        ]
    )
    monkeypatch.setattr(gateway_run, '_submit_quant_cc_analysis', submit, raising=False)
    monkeypatch.setattr(gateway_run, '_poll_quant_cc_task_until_terminal', poll_task, raising=False)
    monkeypatch.setattr(gateway_run, '_get_quant_cc_recommendation_detail', fetch_detail, raising=False)
    monkeypatch.setattr(gateway_run, '_wait_quant_cc_engine_event', wait_event, raising=False)
    monkeypatch.setattr(gateway_run, '_ack_quant_cc_engine_event', ack_event, raising=False)

    result = await runner._handle_message(_make_event('amzn持仓分析'))

    assert result is None
    runner.adapters[Platform.FEISHU].send.assert_awaited_once_with(
        'oc_home',
        '🔍 <b>AMZN 决策依据 #853</b>\n固定策略报告\n\n🔍 <b>AMZN 决策依据 #854</b>\nLLM策略报告',
    )
    assert fetch_detail.await_args_list == [((853,),), ((854,),)]
    ack_event.assert_awaited_once_with(30)
