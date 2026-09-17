"""api-guard plugin — 强制使用 MCP 工具访问受保护 API

拦截 terminal 和 execute_code 工具对特定 API 端点的直接访问，
强制 Agent 使用已注册的 MCP 工具。

受保护端点定义在 _PROTECTED_ENDPOINTS 中，格式：
{
    "endpoint": {
        "tools": ["tool1", "tool2", ...],
        "message": "提示信息"
    }
}
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# 受保护端点配置
# ---------------------------------------------------------------------------

_PROTECTED_ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "localhost:8088": {
        "tools": [
            "dashboard_summary",
            "dashboard_task_status",
            "dashboard_task_calendar",
            "dashboard_task_duration_history",
            "dashboard_next_runs",
            "dashboard_portfolio",
            "dashboard_recent_trades",
            "dashboard_support_resistance",
            "dashboard_options_chain_count",
            "dashboard_options_chain_summary",
            "dashboard_control_service",
            "dashboard_register_service",
            "dashboard_deregister_service",
            "dashboard_real_portfolio",
            "dashboard_update_real_cash",
            "dashboard_add_real_position",
            "dashboard_update_real_position",
            "dashboard_close_real_position",
            "dashboard_get_real_trades",
            "dashboard_add_real_trade",
        ],
        "message": "Dashboard API 必须使用 dashboard_* 工具访问",
    },
    "localhost:8003": {
        "tools": [
            # Market Data Gateway 工具（如有）
        ],
        "message": "Market Data Gateway 必须使用专用工具访问",
    },
}

# 编译正则用于检测命令中的端点
_ENDPOINT_PATTERNS = {
    endpoint: re.compile(re.escape(endpoint))
    for endpoint in _PROTECTED_ENDPOINTS
}


# ---------------------------------------------------------------------------
# 检查函数
# ---------------------------------------------------------------------------

def _check_protected_access(command_or_code: str) -> Optional[str]:
    """检查命令/代码是否尝试访问受保护端点
    
    Returns:
        拦截消息，如果不需要拦截则返回 None
    """
    if not isinstance(command_or_code, str):
        return None
    
    for endpoint, config in _PROTECTED_ENDPOINTS.items():
        pattern = _ENDPOINT_PATTERNS[endpoint]
        if pattern.search(command_or_code):
            tools = config.get("tools", [])
            message = config.get("message", f"禁止直接访问 {endpoint}")
            
            hint = ""
            if tools:
                hint = f"\n\n请使用工具: {', '.join(tools[:3])}"
                if len(tools) > 3:
                    hint += f" 等 {len(tools)} 个工具"
            
            return json.dumps({
                "error": f"禁止直接访问 {endpoint}",
                "reason": message,
                "allowed_tools": tools,
                "hint": hint.strip(),
            }, ensure_ascii=False, indent=2)
    
    return None


# ---------------------------------------------------------------------------
# Hook 回调
# ---------------------------------------------------------------------------

def _on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> Optional[Dict[str, Any]]:
    """pre_tool_call hook — 检查是否尝试访问受保护 API
    
    Returns:
        {"action": "block", "message": "..."} 阻止执行
        None 放行
    """
    if tool_name not in ("terminal", "execute_code"):
        return None
    
    if not isinstance(args, dict):
        return None
    
    # 获取命令/代码内容
    command_or_code = ""
    if tool_name == "terminal":
        command_or_code = args.get("command", "")
    elif tool_name == "execute_code":
        command_or_code = args.get("code", "")
    
    # 检查是否访问受保护端点
    block_message = _check_protected_access(command_or_code)
    if block_message:
        return {
            "action": "block",
            "message": block_message,
        }
    
    return None


# ---------------------------------------------------------------------------
# 插件注册
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """注册插件 hooks"""
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
