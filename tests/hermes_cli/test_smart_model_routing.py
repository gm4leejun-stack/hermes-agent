from hermes_cli.smart_model_routing import is_simple_task, resolve_turn_route


def _routing_cfg():
    return {
        "enabled": True,
        "max_simple_chars": 160,
        "max_simple_words": 28,
        "cheap_model": {
            "provider": "custom",
            "model": "deepseek/deepseek-v4-flash",
            "base_url": "http://gateway.example/v1",
        },
    }


def _primary_runtime():
    return {
        "api_key": "***",
        "base_url": "http://gateway.example/v1",
        "provider": "custom",
        "api_mode": "chat_completions",
        "command": None,
        "args": [],
        "credential_pool": None,
    }


def test_simple_short_prompt_is_simple():
    assert is_simple_task("Reply with exactly: OK", _routing_cfg()) is True


def test_short_debug_prompt_is_not_simple():
    assert is_simple_task("Debug this Python function.", _routing_cfg()) is False


def test_short_structured_output_prompt_is_not_simple():
    assert is_simple_task("Return a JSON schema for this payload.", _routing_cfg()) is False


def test_short_multistep_prompt_is_not_simple():
    assert is_simple_task("First summarize this, then compare two options.", _routing_cfg()) is False


def test_short_reminder_request_is_not_simple():
    assert is_simple_task("3分钟后提醒我见客户开会", _routing_cfg()) is False


def test_short_task_creation_request_is_not_simple():
    assert is_simple_task("明天早上提醒我发周报", _routing_cfg()) is False


def test_route_keeps_primary_for_short_but_complex_prompt():
    route = resolve_turn_route(
        user_message="Return a JSON schema for this payload.",
        primary_model="deepseek/deepseek-v4-pro",
        primary_runtime=_primary_runtime(),
        routing_cfg=_routing_cfg(),
    )

    assert route["model"] == "deepseek/deepseek-v4-pro"
    assert route["runtime"]["provider"] == "custom"


def test_route_keeps_primary_for_short_tool_intent_prompt():
    route = resolve_turn_route(
        user_message="3分钟后提醒我见客户开会",
        primary_model="deepseek/deepseek-v4-pro",
        primary_runtime=_primary_runtime(),
        routing_cfg=_routing_cfg(),
    )

    assert route["model"] == "deepseek/deepseek-v4-pro"
    assert route["runtime"]["provider"] == "custom"
