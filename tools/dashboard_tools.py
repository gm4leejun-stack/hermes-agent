#!/usr/bin/env python3
"""
Dashboard MCP Tools Wrapper

将 Dashboard MCP 工具包装为 Hermes 内部工具，自动发现、无需显式加载。

使用范例：
    dashboard_summary()           # 获取系统概览
    dashboard_task_status(date="2026-04-29")  # 查询任务
    dashboard_support_resistance(symbol="QQQM")  # 查询支撑压力位
"""

import json
from typing import Optional, Dict, Any
from tools.registry import registry

# 内部调用 MCP 工具的辅助函数
def _call_mcp_dashboard(tool_name: str, params: Dict[str, Any]) -> str:
    """调用 dashboard MCP 工具并返回 JSON 字符串"""
    import asyncio
    try:
        # 首先尝试从 hermes_tools 调用（execute_code 沙箱环境）
        try:
            from hermes_tools import globals as ht_globals
            mcp_fn = getattr(ht_globals, f"mcp_dashboard_{tool_name}", None)
            if mcp_fn:
                result = mcp_fn(**params)
                if hasattr(result, 'result'):
                    return result.result
                return str(result)
        except ImportError:
            pass

        # 否则直接通过 MCP 客户端调用
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        
        async def _call():
            server_params = StdioServerParameters(
                command="/opt/homebrew/bin/python3",
                args=["/Users/lijunsheng/project/dashboard/app/mcp_server.py"],
                env={"PYTHONPATH": "/Users/lijunsheng/project/dashboard"}
            )
            
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        tool_name,  # 工具名已经包含 get_ 前缀
                        arguments=params
                    )
                    if result.content and len(result.content) > 0:
                        return result.content[0].text
                    return json.dumps({"error": "Empty result"})
        
        return asyncio.run(_call())
    except Exception as e:
        return json.dumps({"error": str(e)})

# ============================================================================
# 1. 系统监控类工具
# ============================================================================

def dashboard_summary(task_id: Optional[str] = None) -> str:
    """
    获取系统整体概览
    
    返回服务状态、调度器状态、今日任务统计
    """
    return _call_mcp_dashboard("get_dashboard_summary", {})

DASHBOARD_SUMMARY_SCHEMA = {
    "name": "dashboard_summary",
    "description": "【首选】获取 Dashboard 系统整体概览。访问 localhost:8088 必须使用 dashboard_* 工具，禁止用 terminal/execute_code 直接调用。",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

# ============================================================================
# 2. 任务管理类工具
# ============================================================================

def dashboard_task_status(date: Optional[str] = None, project_id: Optional[str] = None) -> str:
    """
    查询特定日期任务状态
    
    Args:
        date: YYYY-MM-DD 格式，默认今天
        project_id: 可选，过滤特定项目（option-agent/market-data-gateway）
    """
    params = {}
    if date:
        params["date"] = date
    if project_id:
        params["project_id"] = project_id
    return _call_mcp_dashboard("get_task_status", params)

DASHBOARD_TASK_STATUS_SCHEMA = {
    "name": "dashboard_task_status",
    "description": "【首选】查询 Dashboard 特定日期任务状态，默认返回今天任务。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "查询日期，YYYY-MM-DD 格式，默认今天"
            },
            "project_id": {
                "type": "string",
                "description": "过滤项目ID（option-agent/market-data-gateway）"
            }
        },
        "required": []
    }
}

def dashboard_task_duration_history(project_id: str, task_id: str, limit: int = 30) -> str:
    """
    获取任务历史耗时
    
    Args:
        project_id: 项目ID
        task_id: 任务ID
        limit: 返回条数，默认30
    """
    return _call_mcp_dashboard("get_task_duration_history", {
        "project_id": project_id,
        "task_id": task_id,
        "limit": limit
    })

DASHBOARD_TASK_DURATION_SCHEMA = {
    "name": "dashboard_task_duration_history",
    "description": "【首选】获取任务历史执行耗时，用于异常检测和性能分析。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "项目ID，如 option-agent, market-data-gateway"
            },
            "task_id": {
                "type": "string",
                "description": "任务ID，如 daily_report_US, cn_eod_sync"
            },
            "limit": {
                "type": "integer",
                "description": "返回历史记录数量，默认30",
                "default": 30
            }
        },
        "required": ["project_id", "task_id"]
    }
}

def dashboard_task_calendar(days: int = 60) -> str:
    """
    获取过去N天任务结果日历
    
    Args:
        days: 天数，默认60天
    """
    return _call_mcp_dashboard("get_task_calendar", {"days": days})

DASHBOARD_TASK_CALENDAR_SCHEMA = {
    "name": "dashboard_task_calendar",
    "description": "【首选】获取过去N天的任务执行结果日历。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "查询天数，默认60天",
                "default": 60
            }
        },
        "required": []
    }
}

def dashboard_recent_trades(
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    market: Optional[str] = None,
    account_type: Optional[str] = None,
) -> str:
    """
    获取最近交易记录（所有账户）
    
    Args:
        date: 单日 YYYY-MM-DD，默认今天
        start_date: 范围起点 YYYY-MM-DD
        end_date: 范围终点 YYYY-MM-DD
        market: 市场 US/HK/CN
        account_type: 账户类型 paper/real
    """
    params = {}
    if date:
        params["date"] = date
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if market:
        params["market"] = market
    if account_type:
        params["account_type"] = account_type
    return _call_mcp_dashboard("get_all_trades", params)

DASHBOARD_RECENT_TRADES_SCHEMA = {
    "name": "dashboard_recent_trades",
    "description": "【首选】获取最近交易记录（所有账户）。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "单日 YYYY-MM-DD，默认今天"
            },
            "start_date": {
                "type": "string",
                "description": "范围起点 YYYY-MM-DD"
            },
            "end_date": {
                "type": "string",
                "description": "范围终点 YYYY-MM-DD"
            },
            "market": {
                "type": "string",
                "description": "市场 US/HK/CN"
            },
            "account_type": {
                "type": "string",
                "description": "账户类型 paper/real"
            }
        },
        "required": []
    }
}

def dashboard_next_runs(project_id: Optional[str] = None) -> str:
    """
    获取任务下次执行时间
    
    Args:
        project_id: 可选，过滤特定项目
    """
    params = {}
    if project_id:
        params["project_id"] = project_id
    return _call_mcp_dashboard("get_next_runs", params)

DASHBOARD_NEXT_RUNS_SCHEMA = {
    "name": "dashboard_next_runs",
    "description": "【首选】获取定时任务的下次执行时间。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "过滤项目ID"
            }
        },
        "required": []
    }
}

# ============================================================================
# 3. 财务数据类工具
# ============================================================================

def dashboard_portfolio() -> str:
    """获取账户持仑信息"""
    return _call_mcp_dashboard("get_portfolio", {})

DASHBOARD_PORTFOLIO_SCHEMA = {
    "name": "dashboard_portfolio",
    "description": "【首选】获取投资组合持仑信息。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

def dashboard_options_chain_count(symbol: str) -> str:
    """
    获取期权链合约数量

    Args:
        symbol: 股票代码（如 QQQM）
    """
    return _call_mcp_dashboard("get_options_chain_count", {"symbol": symbol})

DASHBOARD_OPTIONS_CHAIN_SCHEMA = {
    "name": "dashboard_options_chain_count",
    "description": "【首选】获取指定股票的期权链合约数量。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "股票代码，如 QQQM, SPY, AAPL"
            }
        },
        "required": ["symbol"]
    }
}

def dashboard_options_chain_summary(date: Optional[str] = None) -> str:
    """
    获取所有市场期权链聚合统计（运维日报数据同步质量检查专用）

    返回每个市场的标的数、总合约数、平均单标的合约数，无需逐个标的查询。

    Args:
        date: YYYY-MM-DD 格式，默认昨天
    """
    params = {}
    if date:
        params["date"] = date
    return _call_mcp_dashboard("get_options_chain_summary", params)

DASHBOARD_OPTIONS_CHAIN_SUMMARY_SCHEMA = {
    "name": "dashboard_options_chain_summary",
    "description": "【首选】获取所有市场期权链聚合统计，返回 symbol_count（标的数）、total_contracts（总合约数）、avg_per_symbol（平均合约数）。运维日报期权链数据同步质量检查必用此工具。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "查询日期，YYYY-MM-DD 格式，默认昨天"
            }
        },
        "required": []
    }
}

def dashboard_analysis_run(symbol: str, date: str) -> str:
    """查询指定标的在指定日期的机会分析结果（JuhuFaxian 完整输出）。"""
    return _call_mcp_dashboard("get_analysis_run", {"symbol": symbol, "date": date})

def dashboard_decisions(date: str = None) -> str:
    """查询调度器决策日志 — 当天分析了哪些标的、各自结论是什么。date 默认今天。"""
    params = {}
    if date:
        params["date"] = date
    return _call_mcp_dashboard("get_decisions", params)

def dashboard_run_analysis(
    symbol: str, date: str, market: str = "US", direction: str = "CSP_OPEN",
    position_dte: int = None, position_entry_premium: float = None,
    position_strike: float = None, position_id: str = None,
) -> str:
    """触发 JuhuFaxian 机会分析（支持开仓/平仓四方向）。
    
    Args:
        symbol: 标的代码
        date: 分析日期 YYYY-MM-DD
        market: 市场 US/HK
        direction: CSP_OPEN | CC_OPEN | CC_CLOSE | CSP_CLOSE
        position_dte: (平仓) 当前持仓DTE
        position_entry_premium: (平仓) 开仓权利金
        position_strike: (平仓) 持仓行权价
        position_id: (平仓) 持仓ID
    """
    params = {"symbol": symbol.upper(), "date": date, "market": market, "direction": direction}
    if position_dte is not None:
        params["position_dte"] = position_dte
    if position_entry_premium is not None:
        params["position_entry_premium"] = position_entry_premium
    if position_strike is not None:
        params["position_strike"] = position_strike
    if position_id is not None:
        params["position_id"] = position_id
    return _call_mcp_dashboard("run_analysis", params)

def dashboard_scheduler_history(limit: int = 50) -> str:
    """查询调度器最近任务执行历史（任务名、状态、耗时）。"""
    return _call_mcp_dashboard("get_scheduler_history", {"limit": limit})

registry.register(
    name="dashboard_analysis_run",
    toolset="dashboard", emoji="🔬",
    schema={"name": "dashboard_analysis_run",
            "description": (
                "【首选】查询指定标的在指定日期的机会分析结果。访问 localhost:8088 必须使用 dashboard_* 工具。"
                "结果在 run.state_json。"
                "【computed_indicators 字段规则】展示'入场窗口天数'必须用 days_in_entry_window，"
                "禁止用 days_since_shock_end（仅遗留字段）。"
                "【execution_result v3 字段】"
                "trade=null 时查 rejection_reason（常见值：option_chain_missing / "
                "no_support_candidates_from_gateway / no_support_candidates_after_filter / "
                "no_valid_put_contract_all_anchors）；"
                "anchor_tried_log 列出每个支撑档的尝试记录（mode/status/reason）；"
                "structure.support_candidates_count 为参与搜索的候选支撑数。"
            ),
            "parameters": {"type": "object", "properties": {
                "symbol": {"type": "string", "description": "股票代码，如 SPY"},
                "date": {"type": "string", "description": "YYYY-MM-DD"}},
                "required": ["symbol", "date"]}},
    handler=lambda args, **kw: dashboard_analysis_run(args["symbol"], args["date"]),
)

registry.register(
    name="dashboard_decisions",
    toolset="dashboard", emoji="📋",
    schema={"name": "dashboard_decisions",
            "description": "【首选】查询调度器决策日志，了解当天分析了哪些标的及结论。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD，默认今天"}},
                "required": []}},
    handler=lambda args, **kw: dashboard_decisions(args.get("date")),
)

registry.register(
    name="dashboard_run_analysis",
    toolset="dashboard", emoji="🚀",
    schema={"name": "dashboard_run_analysis",
            "description": "【触发】JuhuFaxian 机会分析，支持四方向（CSP_OPEN/CC_OPEN/CC_CLOSE/CSP_CLOSE）。开仓返回交易参数，平仓返回平仓信号。",
            "parameters": {"type": "object", "properties": {
                "symbol": {"type": "string", "description": "标的代码，如 SPY、AAPL"},
                "date": {"type": "string", "description": "分析日期 YYYY-MM-DD"},
                "market": {"type": "string", "description": "市场 US/HK，默认 US"},
                "direction": {"type": "string", "description": "CSP_OPEN | CC_OPEN | CC_CLOSE | CSP_CLOSE，默认 CSP_OPEN"},
                "position_dte": {"type": "integer", "description": "（平仓）当前持仓DTE"},
                "position_entry_premium": {"type": "number", "description": "（平仓）开仓权利金"},
                "position_strike": {"type": "number", "description": "（平仓）持仓行权价"},
                "position_id": {"type": "string", "description": "（平仓）持仓ID"}},
                "required": ["symbol", "date"]}},
    handler=lambda args, **kw: dashboard_run_analysis(
        args["symbol"], args["date"], args.get("market", "US"), args.get("direction", "CSP_OPEN"),
        args.get("position_dte"), args.get("position_entry_premium"),
        args.get("position_strike"), args.get("position_id")),
)

registry.register(
    name="dashboard_scheduler_history",
    toolset="dashboard", emoji="📊",
    schema={"name": "dashboard_scheduler_history",
            "description": "【首选】查询调度器最近任务执行历史。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "返回条数，默认 50"}},
                "required": []}},
    handler=lambda args, **kw: dashboard_scheduler_history(args.get("limit", 50)),
)

# ============================================================================
# 4. 技术分析类工具
# ============================================================================

def dashboard_support_resistance(symbol: str, date: Optional[str] = None) -> str:
    """
    查询股票支撑压力位
    
    重要：必须使用此接口，禁止自行计算
    
    Args:
        symbol: 股票代码
        date: YYYY-MM-DD 格式，默认今天
    """
    params = {"symbol": symbol}
    if date:
        params["date"] = date
    return _call_mcp_dashboard("get_support_resistance", params)

DASHBOARD_SUPPORT_RESISTANCE_SCHEMA = {
    "name": "dashboard_support_resistance",
    "description": "【首选】查询股票支撑压力位。重要：必须使用此接口，禁止自行计算。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "股票代码，如 QQQM, SPY"
            },
            "date": {
                "type": "string",
                "description": "日期，YYYY-MM-DD 格式，默认今天"
            }
        },
        "required": ["symbol"]
    }
}

# ============================================================================
# 5. 真实账户工具
# ============================================================================

def dashboard_real_portfolio() -> str:
    """
    查询真实账户持仓和账户余额

    返回真实账户（非模拟）的持仓列表、各市场账户余额、保证金使用情况。
    当需要查看实际持仓时使用此接口，不要使用 get_portfolio（那是模拟账户）。
    """
    return _call_mcp_dashboard("get_real_portfolio", {})

DASHBOARD_REAL_PORTFOLIO_SCHEMA = {
    "name": "dashboard_real_portfolio",
    "description": "【首选】查询真实账户持仓和账户余额（非模拟账户）。访问 localhost:8088 必须使用 dashboard_* 工具。",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

registry.register(
    name="dashboard_real_portfolio",
    toolset="dashboard",
    emoji="💼",
    schema=DASHBOARD_REAL_PORTFOLIO_SCHEMA,
    handler=lambda args, **kw: dashboard_real_portfolio(),
)

def dashboard_update_real_cash(market: str, cash: float) -> str:
    """更新真实账户现金余额。market: US/CN/HK，cash: 当地货币金额。"""
    return _call_mcp_dashboard("update_real_cash", {"market": market, "cash": cash})

def dashboard_add_real_position(
    symbol: str, strategy_type: str, contracts: int, entry_premium: float,
    entry_date: str, market: str = "US", strike: float = 0.0,
    expiry: str = "2099-12-31", current_price: float = 0.0,
) -> str:
    """添加真实账户持仓记录。"""
    # MCP 工具会在内部生成 position_id, dte, Greeks 等字段
    # 这里只传入用户可见的参数
    params = {
        "symbol": symbol,
        "strategy_type": strategy_type.upper(),
        "contracts": contracts,
        "entry_premium": entry_premium,
        "entry_date": entry_date,
        "market": market,
        "current_price": current_price,
    }
    if strike:
        params["strike"] = strike
    if expiry and expiry != "2099-12-31":
        params["expiry"] = expiry
    return _call_mcp_dashboard("add_real_position", params)

def dashboard_update_real_position(position_id: str, **fields) -> str:
    """更新真实账户持仓字段（contracts/entry_premium/current_price/strike/expiry）。"""
    params = {"position_id": position_id}
    params.update({k: v for k, v in fields.items() if v is not None})
    return _call_mcp_dashboard("update_real_position", params)

def dashboard_close_real_position(position_id: str) -> str:
    """平仓真实账户持仓。"""
    return _call_mcp_dashboard("delete_real_position", {"position_id": position_id})

def dashboard_get_real_trades(
    date: str = None,
    start_date: str = None,
    end_date: str = None,
    market: str = None,
) -> str:
    """查询真实账户成交记录（account_type=real 固定）。
    date 优先于 start/end_date；不传日期默认今日。
    """
    params = {"account_type": "real"}
    if date:        params["date"] = date
    if start_date:  params["start_date"] = start_date
    if end_date:    params["end_date"] = end_date
    if market:      params["market"] = market
    return _call_mcp_dashboard("get_all_trades", params)

def dashboard_add_real_trade(
    market: str, symbol: str, side: str, qty: int, price: float,
    trade_date: str, code: str = "", trade_time: str = "",
) -> str:
    """记录真实账户成交。side: buy/sell。"""
    return _call_mcp_dashboard("add_real_trade", {
        "market": market, "symbol": symbol, "side": side,
        "qty": qty, "price": price, "trade_date": trade_date,
        "code": code, "trade_time": trade_time,
    })

def dashboard_delete_real_trade(trade_id: str) -> str:
    """删除真实账户成交记录。"""
    return _call_mcp_dashboard("delete_real_trade", {"trade_id": trade_id})


registry.register(
    name="dashboard_update_real_cash",
    toolset="dashboard", emoji="💰",
    schema={"name": "dashboard_update_real_cash", "description": "【首选】更新真实账户现金余额。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "market": {"type": "string", "description": "US / CN / HK"},
                "cash": {"type": "number", "description": "新余额（当地货币）"}},
                "required": ["market", "cash"]}},
    handler=lambda args, **kw: dashboard_update_real_cash(args["market"], args["cash"]),
)

registry.register(
    name="dashboard_add_real_position",
    toolset="dashboard", emoji="➕",
    schema={"name": "dashboard_add_real_position", "description": "【首选】添加真实账户持仓记录。访问 localhost:8088 必须使用 dashboard_* 工具。股票持仓 strategy_type 填 STOCK。",
            "parameters": {"type": "object", "properties": {
                "symbol": {"type": "string"}, 
                "strategy_type": {"type": "string", "description": "STOCK/CC/CSP 等"},
                "contracts": {"type": "integer"}, 
                "entry_premium": {"type": "number", "description": "成本价"},
                "entry_date": {"type": "string", "description": "YYYY-MM-DD"},
                "market": {"type": "string", "description": "US/CN/HK，默认 US"},
                "strike": {"type": "number", "description": "期权行权价，股票填 0"},
                "expiry": {"type": "string", "description": "YYYY-MM-DD，股票填 2099-12-31"},
                "current_price": {"type": "number", "description": "当前价，默认 0"}},
                "required": ["symbol", "strategy_type", "contracts", "entry_premium", "entry_date"]}},
    handler=lambda args, **kw: dashboard_add_real_position(**args),
)

registry.register(
    name="dashboard_update_real_position",
    toolset="dashboard", emoji="✏️",
    schema={"name": "dashboard_update_real_position", "description": "【首选】更新真实账户持仓字段。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "position_id": {"type": "string"},
                "contracts": {"type": "integer"}, "entry_premium": {"type": "number"},
                "current_price": {"type": "number"}, "strike": {"type": "number"},
                "expiry": {"type": "string"}},
                "required": ["position_id"]}},
    handler=lambda args, **kw: dashboard_update_real_position(**args),
)

registry.register(
    name="dashboard_close_real_position",
    toolset="dashboard", emoji="❌",
    schema={"name": "dashboard_close_real_position", "description": "【首选】平仓真实账户持仓。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "position_id": {"type": "string", "description": "持仓ID"}},
                "required": ["position_id"]}},
    handler=lambda args, **kw: dashboard_close_real_position(args["position_id"]),
)

registry.register(
    name="dashboard_get_real_trades",
    toolset="dashboard", emoji="📋",
    schema={"name": "dashboard_get_real_trades",
            "description": "【首选】查询真实账户成交记录（account_type=real）。支持日期/市场过滤。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "date":       {"type": "string", "description": "单日 YYYY-MM-DD，默认今日"},
                "start_date": {"type": "string", "description": "范围起点 YYYY-MM-DD"},
                "end_date":   {"type": "string", "description": "范围终点 YYYY-MM-DD"},
                "market":     {"type": "string", "description": "US/HK/CN，不传=全部"},
            }, "required": []}},
    handler=lambda args, **kw: dashboard_get_real_trades(
        date=args.get("date"), start_date=args.get("start_date"),
        end_date=args.get("end_date"), market=args.get("market"),
    ),
)

registry.register(
    name="dashboard_add_real_trade",
    toolset="dashboard", emoji="📝",
    schema={"name": "dashboard_add_real_trade", "description": "【首选】记录真实账户成交。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "market": {"type": "string", "description": "US/CN/HK"},
                "symbol": {"type": "string"}, "side": {"type": "string", "description": "buy 或 sell"},
                "qty": {"type": "integer"}, "price": {"type": "number"},
                "trade_date": {"type": "string", "description": "YYYY-MM-DD"},
                "code": {"type": "string"}, "trade_time": {"type": "string"}},
                "required": ["market", "symbol", "side", "qty", "price", "trade_date"]}},
    handler=lambda args, **kw: dashboard_add_real_trade(**args),
)

registry.register(
    name="dashboard_delete_real_trade",
    toolset="dashboard", emoji="🗑️",
    schema={"name": "dashboard_delete_real_trade", "description": "【首选】删除真实账户成交记录。访问 localhost:8088 必须使用 dashboard_* 工具。",
            "parameters": {"type": "object", "properties": {
                "trade_id": {"type": "string"}},
                "required": ["trade_id"]}},
    handler=lambda args, **kw: dashboard_delete_real_trade(args["trade_id"]),
)

# ============================================================================
# 6. 服务管理类工具
# ============================================================================

def dashboard_register_service(
    id: str,
    name: str,
    group_id: str,
    group_label: str,
    check_type: str,
    launchctl_label: str,
    group_icon: str = "",
    group_host: str = "",
    url: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    binary: Optional[str] = None,
    args: Optional[list] = None,
    workdir: Optional[str] = None,
    check_command: Optional[str] = None,
    actions: Optional[dict] = None,
) -> str:
    """
    注册新服务到 Dashboard 监控
    
    如果提供 binary，会生成 plist 并通过 launchctl 加载（KeepAlive=true）。
    如果不提供 binary，仅注册服务进行健康监控。
    
    Args:
        id: 服务唯一ID，如 'market-data-gateway'
        name: 服务显示名称
        group_id: 所属分组ID
        group_label: 分组显示名称
        check_type: 健康检查类型（http/http_rich/tcp/self）
        launchctl_label: launchd 标签，如 'com.market-data-gateway'
        group_icon: 分组图标（emoji）
        group_host: 分组主机地址显示
        url: HTTP 健康检查 URL（http/http_rich 必需）
        host: TCP 检查主机（tcp 必需）
        port: TCP 检查端口（tcp 必需）
        binary: 可执行文件路径（触发 plist 生成）
        args: 命令行参数列表
        workdir: 工作目录
        check_command: 自定义状态检测命令（check_type=self 时使用）
        actions: 操作命令字典，如 {"connect": "vpn-connect.sh", "disconnect": "vpn-disconnect.sh"}
    """
    params = {
        "id": id,
        "name": name,
        "group_id": group_id,
        "group_label": group_label,
        "check_type": check_type,
        "launchctl_label": launchctl_label,
        "group_icon": group_icon,
        "group_host": group_host,
    }
    if url is not None:
        params["url"] = url
    if host is not None:
        params["host"] = host
    if port is not None:
        params["port"] = port
    if binary is not None:
        params["binary"] = binary
    if args is not None:
        params["args"] = args
    if workdir is not None:
        params["workdir"] = workdir
    if check_command is not None:
        params["check_command"] = check_command
    if actions is not None:
        params["actions"] = actions
    return _call_mcp_dashboard("register_service", params)

DASHBOARD_REGISTER_SERVICE_SCHEMA = {
    "name": "dashboard_register_service",
    "description": "注册新服务到 Dashboard 监控。如果提供 binary，会生成 plist 并通过 launchctl 加载；否则仅注册健康监控。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "服务唯一ID，如 'market-data-gateway'"
            },
            "name": {
                "type": "string",
                "description": "服务显示名称"
            },
            "group_id": {
                "type": "string",
                "description": "所属分组ID"
            },
            "group_label": {
                "type": "string",
                "description": "分组显示名称"
            },
            "check_type": {
                "type": "string",
                "description": "健康检查类型：http, http_rich, tcp, self",
                "enum": ["http", "http_rich", "tcp", "self"]
            },
            "launchctl_label": {
                "type": "string",
                "description": "launchd 标签，如 'com.market-data-gateway'"
            },
            "group_icon": {
                "type": "string",
                "description": "分组图标（emoji）",
                "default": ""
            },
            "group_host": {
                "type": "string",
                "description": "分组主机地址显示，如 'localhost:8003'",
                "default": ""
            },
            "url": {
                "type": "string",
                "description": "HTTP 健康检查 URL（http/http_rich 必需）"
            },
            "host": {
                "type": "string",
                "description": "TCP 检查主机（tcp 必需）"
            },
            "port": {
                "type": "integer",
                "description": "TCP 检查端口（tcp 必需）"
            },
            "binary": {
                "type": "string",
                "description": "可执行文件绝对路径（触发 plist 生成）"
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "命令行参数列表"
            },
            "workdir": {
                "type": "string",
                "description": "工作目录"
            },
            "check_command": {
                "type": "string",
                "description": "自定义状态检测命令（check_type=self 时使用）"
            },
            "actions": {
                "type": "object",
                "description": "操作命令字典，如 {\"connect\": \"vpn-connect.sh\", \"disconnect\": \"vpn-disconnect.sh\"}"
            }
        },
        "required": ["id", "name", "group_id", "group_label", "check_type", "launchctl_label"]
    }
}

def dashboard_deregister_service(service_id: str, stop: bool = True) -> str:
    """
    从 Dashboard 注销服务
    
    Args:
        service_id: 要注销的服务ID，如 'market-data-gateway'
        stop: 是否停止进程并删除 plist（默认 True）
    """
    return _call_mcp_dashboard("deregister_service", {
        "service_id": service_id,
        "stop": stop
    })

DASHBOARD_DEREGISTER_SERVICE_SCHEMA = {
    "name": "dashboard_deregister_service",
    "description": "从 Dashboard 注销服务。可选停止进程并删除 plist。",
    "parameters": {
        "type": "object",
        "properties": {
            "service_id": {
                "type": "string",
                "description": "要注销的服务ID，如 'market-data-gateway'"
            },
            "stop": {
                "type": "boolean",
                "description": "是否停止进程并删除 plist，默认 True",
                "default": True
            }
        },
        "required": ["service_id"]
    }
}

def dashboard_control_service(service_id: str, action: str) -> str:
    """
    执行服务预定义操作
    
    Args:
        service_id: 服务ID，如 'vpn-service'
        action: 操作名称，如 'connect', 'disconnect'
    """
    return _call_mcp_dashboard("control_service", {
        "service_id": service_id,
        "action": action
    })

DASHBOARD_CONTROL_SERVICE_SCHEMA = {
    "name": "dashboard_control_service",
    "description": "执行服务预定义操作（如 connect / disconnect）",
    "parameters": {
        "type": "object",
        "properties": {
            "service_id": {
                "type": "string",
                "description": "服务ID，如 'vpn-service'"
            },
            "action": {
                "type": "string",
                "description": "操作名称，如 'connect', 'disconnect'"
            }
        },
        "required": ["service_id", "action"]
    }
}

# ============================================================================
# 工具注册
# ============================================================================

# 系统监控
registry.register(
    name="dashboard_summary",
    toolset="dashboard",
    emoji="📊",
    schema=DASHBOARD_SUMMARY_SCHEMA,
    handler=lambda args, **kw: dashboard_summary(),
)

# 任务管理
registry.register(
    name="dashboard_task_status",
    toolset="dashboard",
    emoji="📋",
    schema=DASHBOARD_TASK_STATUS_SCHEMA,
    handler=lambda args, **kw: dashboard_task_status(
        date=args.get("date"),
        project_id=args.get("project_id")
    ),
)

registry.register(
    name="dashboard_task_duration_history",
    toolset="dashboard",
    emoji="⏱️",
    schema=DASHBOARD_TASK_DURATION_SCHEMA,
    handler=lambda args, **kw: dashboard_task_duration_history(
        project_id=args["project_id"],
        task_id=args["task_id"],
        limit=args.get("limit", 30)
    ),
)

registry.register(
    name="dashboard_task_calendar",
    toolset="dashboard",
    emoji="📅",
    schema=DASHBOARD_TASK_CALENDAR_SCHEMA,
    handler=lambda args, **kw: dashboard_task_calendar(args.get("days", 60)),
)

registry.register(
    name="dashboard_next_runs",
    toolset="dashboard",
    emoji="⏰",
    schema=DASHBOARD_NEXT_RUNS_SCHEMA,
    handler=lambda args, **kw: dashboard_next_runs(args.get("project_id")),
)

# 财务数据
registry.register(
    name="dashboard_portfolio",
    toolset="dashboard",
    emoji="💰",
    schema=DASHBOARD_PORTFOLIO_SCHEMA,
    handler=lambda args, **kw: dashboard_portfolio(),
)

registry.register(
    name="dashboard_recent_trades",
    toolset="dashboard",
    emoji="📈",
    schema=DASHBOARD_RECENT_TRADES_SCHEMA,
    handler=lambda args, **kw: dashboard_recent_trades(
        date=args.get("date"), 
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        market=args.get("market"),
        account_type=args.get("account_type"),
    ),
)

registry.register(
    name="dashboard_options_chain_count",
    toolset="dashboard",
    emoji="📉",
    schema=DASHBOARD_OPTIONS_CHAIN_SCHEMA,
    handler=lambda args, **kw: dashboard_options_chain_count(args["symbol"]),
)

registry.register(
    name="dashboard_options_chain_summary",
    toolset="dashboard",
    emoji="📊",
    schema=DASHBOARD_OPTIONS_CHAIN_SUMMARY_SCHEMA,
    handler=lambda args, **kw: dashboard_options_chain_summary(args.get("date")),
)

# 技术分析
registry.register(
    name="dashboard_support_resistance",
    toolset="dashboard",
    emoji="📈",
    schema=DASHBOARD_SUPPORT_RESISTANCE_SCHEMA,
    handler=lambda args, **kw: dashboard_support_resistance(
        symbol=args["symbol"],
        date=args.get("date")
    ),
)

# 服务管理
registry.register(
    name="dashboard_register_service",
    toolset="dashboard",
    emoji="➕",
    schema=DASHBOARD_REGISTER_SERVICE_SCHEMA,
    handler=lambda args, **kw: dashboard_register_service(
        id=args["id"],
        name=args["name"],
        group_id=args["group_id"],
        group_label=args["group_label"],
        check_type=args["check_type"],
        launchctl_label=args["launchctl_label"],
        group_icon=args.get("group_icon", ""),
        group_host=args.get("group_host", ""),
        url=args.get("url"),
        host=args.get("host"),
        port=args.get("port"),
        binary=args.get("binary"),
        args=args.get("args"),
        workdir=args.get("workdir"),
        check_command=args.get("check_command"),
        actions=args.get("actions"),
    ),
)

registry.register(
    name="dashboard_deregister_service",
    toolset="dashboard",
    emoji="➖",
    schema=DASHBOARD_DEREGISTER_SERVICE_SCHEMA,
    handler=lambda args, **kw: dashboard_deregister_service(
        service_id=args["service_id"],
        stop=args.get("stop", True)
    ),
)

registry.register(
    name="dashboard_control_service",
    toolset="dashboard",
    emoji="🎮",
    schema=DASHBOARD_CONTROL_SERVICE_SCHEMA,
    handler=lambda args, **kw: dashboard_control_service(
        service_id=args["service_id"],
        action=args["action"]
    ),
)