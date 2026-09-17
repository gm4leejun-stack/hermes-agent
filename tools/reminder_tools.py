#!/usr/bin/env python3
"""
Smart Reminder Tools - 智能提醒工具

模块二：基础提醒功能（执行层）
- 纯确定性执行，不依赖 LLM 和 prompt
- content 原样存储，到点原样发送
- 直接使用 cronjob 存储，用名称前缀识别

设计原则：
1. 执行层只接收结构化参数（精确时间、明确内容）
2. 不做语义理解，不做推理
3. 到点直接发送消息，无 LLM 介入
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from tools.registry import registry

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 提醒任务名称前缀，用于从 cronjob 中识别提醒
REMINDER_NAME_PREFIX = "⏰ 提醒: "

# cronjob 存储路径
HERMES_DIR = os.path.expanduser("~/.hermes")
CRON_JOBS_FILE = os.path.join(HERMES_DIR, "cron", "jobs.json")


# ============================================================================
# 时间解析辅助函数
# ============================================================================


# ============================================================================
# 版本兼容性检查
# ============================================================================

def _check_dependencies() -> Dict[str, bool]:
    """
    检查依赖模块是否可用
    
    Returns:
        {"cron.jobs": bool, ...}
    """
    deps = {}
    
    try:
        from cron.jobs import create_job, save_jobs, load_jobs
        deps["cron.jobs"] = True
    except ImportError:
        deps["cron.jobs"] = False
    
    return deps


def _ensure_dependencies():
    """确保依赖可用，否则抛出友好错误"""
    deps = _check_dependencies()
    
    if not deps.get("cron.jobs"):
        raise ImportError(
            "❌ 智能提醒工具依赖 cron.jobs 模块\n"
            "可能原因：\n"
            "1. Hermes Agent 版本不兼容\n"
            "2. cron 模块未正确安装\n"
            "\n"
            "请尝试：\n"
            "1. 检查 Hermes Agent 版本\n"
            "2. 重新安装 Hermes Agent\n"
            "3. 联系开发者获取支持"
        )


# 启动时检查（延迟到首次使用时）
_DEPENDENCIES_CHECKED = False

def _parse_time_to_iso(time_str: str) -> str:
    """
    将时间字符串转换为 ISO 格式
    
    支持：
    - ISO 格式：2026-05-24T23:00:00
    - 日期时间：2026-05-24 23:00
    - 相对时间：+30m, +1h, +2d
    - 时间戳：1716566400
    """
    # 已经是 ISO 格式
    if "T" in time_str:
        return time_str
    
    # 日期时间格式
    if " " in time_str and "-" in time_str:
        return time_str.replace(" ", "T")
    
    # 相对时间
    if time_str.startswith("+"):
        return _parse_relative_time(time_str)
    
    # 时间戳
    try:
        ts = int(time_str)
        return datetime.fromtimestamp(ts).isoformat()
    except ValueError:
        pass
    
    # 原样返回
    return time_str


def _parse_relative_time(rel_str: str) -> str:
    """解析相对时间：+30m, +1h, +2d"""
    now = datetime.now()
    
    try:
        num = int(rel_str[1:-1])
        unit = rel_str[-1].lower()
        
        if unit == "m":
            delta = timedelta(minutes=num)
        elif unit == "h":
            delta = timedelta(hours=num)
        elif unit == "d":
            delta = timedelta(days=num)
        else:
            return rel_str
        
        return (now + delta).isoformat()
    except (ValueError, IndexError):
        return rel_str


def _time_to_cron(time_str: str, repeat: str) -> str:
    """
    将时间转换为 cron 表达式或 ISO 时间戳
    
    Args:
        time_str: ISO 时间或 HH:MM 格式
        repeat: once / daily / weekly / monthly
    
    Returns:
        cron 表达式或 ISO 时间戳
    """
    # 一次性任务：返回 ISO 时间戳
    if repeat == "once":
        return _parse_time_to_iso(time_str)
    
    # 解析时间
    try:
        if "T" in time_str:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        elif ":" in time_str:
            hour, minute = time_str.split(":")
            dt = datetime.now().replace(hour=int(hour), minute=int(minute), second=0)
        else:
            return time_str
    except Exception:
        return time_str
    
    hour = dt.hour
    minute = dt.minute
    day = dt.day
    
    if repeat == "daily":
        return f"{minute} {hour} * * *"
    elif repeat == "weekly":
        weekday = dt.weekday()
        return f"{minute} {hour} * * {weekday}"
    elif repeat == "monthly":
        return f"{minute} {hour} {day} * *"
    else:
        return f"{minute} {hour} * * *"


# ============================================================================
# Cronjob 操作
# ============================================================================

def _get_hermes_bin() -> str:
    """获取 hermes 可执行文件路径"""
    # 尝试从 Python 解释器路径推断
    hermes_bin = sys.executable.replace("python", "hermes")
    if os.path.exists(hermes_bin):
        return hermes_bin
    
    # 尝试 PATH
    return "hermes"


def _run_hermes_cron(args: List[str]) -> Dict[str, Any]:
    """
    执行 hermes cron 命令（备用方案，用于删除等操作）
    
    Returns:
        {"success": bool, "output": str, "error": str}
    """
    hermes_bin = _get_hermes_bin()
    cmd = [hermes_bin, "cron"] + args
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }


def _create_cronjob_directly(
    content: str,
    schedule: str,
    name: str,
    repeat: int,
    platform: str
) -> Dict[str, Any]:
    """
    直接调用 cron.jobs.create_job() 创建任务
    
    Returns:
        {"success": bool, "job_id": str, "error": str}
    """
    try:
        from cron.jobs import create_job, save_jobs, load_jobs
        
        # 创建任务
        # 注意：不使用 no_agent，而是设置一个简单的 prompt
        # 让 agent 直接输出提醒内容
        prompt = f"直接输出以下内容（不要添加任何额外文字）：\n\n{content}"
        
        job = create_job(
            prompt=prompt,           # 提醒内容（包装后的）
            schedule=schedule,       # 时间
            name=name,               # 任务名称
            repeat=repeat,           # 重复次数（1=一次，None=永久）
            deliver=platform,        # 发送平台
            enabled_toolsets=[]      # 禁用所有工具，减少开销
        )
        
        # 保存（去重）
        jobs = load_jobs()
        job_id = job.get("id", "")
        
        # 移除已存在的相同 id 任务
        jobs = [j for j in jobs if j.get("id") != job_id]
        jobs.append(job)
        save_jobs(jobs)
        
        return {
            "success": True,
            "job_id": job.get("id", "")  # job_id 在 'id' 字段
        }
        
    except Exception as e:
        logger.error(f"Failed to create cronjob directly: {e}")
        return {
            "success": False,
            "job_id": "",
            "error": str(e)
        }


def _load_cron_jobs() -> List[Dict[str, Any]]:
    """加载 cronjob 列表"""
    if not os.path.exists(CRON_JOBS_FILE):
        return []
    
    try:
        with open(CRON_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 支持两种格式：{"jobs": [...]} 或 [...]
            if isinstance(data, dict):
                return data.get("jobs", [])
            elif isinstance(data, list):
                return data
            return []
    except Exception as e:
        logger.error(f"Failed to load cron jobs: {e}")
        return []


def _save_cron_jobs(jobs: List[Dict[str, Any]]) -> bool:
    """保存 cronjob 列表"""
    try:
        os.makedirs(os.path.dirname(CRON_JOBS_FILE), exist_ok=True)
        with open(CRON_JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save cron jobs: {e}")
        return False


def _is_reminder_job(job: Dict[str, Any]) -> bool:
    """判断是否为提醒任务"""
    name = job.get("name", "")
    return name.startswith(REMINDER_NAME_PREFIX.strip())


def _extract_content_from_name(name: str) -> str:
    """从任务名称中提取提醒内容"""
    if name.startswith(REMINDER_NAME_PREFIX.strip()):
        return name[len(REMINDER_NAME_PREFIX.strip()):]
    return name


# ============================================================================
# 核心功能：创建提醒
# ============================================================================

def reminder_create(
    content: str,
    time: str,
    repeat: str = "once",
    platform: str = "wecom"
) -> str:
    """
    创建提醒任务
    
    Args:
        content: 提醒内容（原样存储，到点原样发送）
        time: 提醒时间（ISO 格式、日期时间、相对时间）
        repeat: 重复模式 - once / daily / weekly / monthly
        platform: 发送平台 - wecom / telegram / feishu
    
    Returns:
        JSON 结果
    
    设计原则：
        - 执行层不做语义理解，只接收精确参数
        - content 原样存储，到点直接发送
        - 内部调用 cronjob，无 LLM 介入
    """
    try:
        # 检查依赖（首次调用时）
        global _DEPENDENCIES_CHECKED
        if not _DEPENDENCIES_CHECKED:
            _ensure_dependencies()
            _DEPENDENCIES_CHECKED = True
        
        # 解析时间
        iso_time = _parse_time_to_iso(time)
        schedule = _time_to_cron(iso_time, repeat)
        
        # 验证时间未过期（仅一次性任务）
        if repeat == "once":
            try:
                reminder_time = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
                if reminder_time < datetime.now():
                    return json.dumps({
                        "success": False,
                        "error": "提醒时间已过期，请选择未来的时间"
                    }, ensure_ascii=False)
            except Exception:
                pass
        
        # 检查是否已存在相同内容的提醒
        jobs = _load_cron_jobs()
        job_name_prefix = f"{REMINDER_NAME_PREFIX.strip()}{content[:30]}"
        for job in jobs:
            if job.get("name") == job_name_prefix:
                # 已存在相同提醒
                return json.dumps({
                    "success": False,
                    "error": "已存在相同内容的提醒",
                    "existing_job_id": job.get("id"),
                    "existing_next_run": job.get("next_run_at")
                }, ensure_ascii=False)
        
        # 任务名称
        job_name = job_name_prefix
        
        # 重复次数
        repeat_count = 1 if repeat == "once" else None
        
        # 直接调用 cron API 创建任务
        result = _create_cronjob_directly(
            content=content,
            schedule=schedule,
            name=job_name,
            repeat=repeat_count,
            platform=platform
        )
        
        if result["success"]:
            return json.dumps({
                "success": True,
                "job_id": result["job_id"],
                "content": content,
                "next_run": iso_time,
                "repeat": repeat,
                "platform": platform
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error", "创建提醒失败")
            }, ensure_ascii=False)
            
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def _extract_job_id_from_output(output: str) -> str:
    """从 hermes cron create 输出中提取 job_id"""
    # 输出格式可能是：
    # - "Created job: abc123"
    # - "job_id: abc123"
    # - JSON 格式
    
    import re
    
    # 尝试匹配 job_id
    match = re.search(r'job_id["\s:]+([a-f0-9]+)', output, re.IGNORECASE)
    if match:
        return match.group(1)
    
    match = re.search(r'Created job[:\s]+([a-f0-9]+)', output, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return ""


# ============================================================================
# 核心功能：查询提醒
# ============================================================================

def reminder_list(
    active_only: bool = True,
    platform: str = None
) -> str:
    """
    查询提醒列表
    
    Args:
        active_only: 仅显示未完成的提醒
        platform: 过滤平台
    
    Returns:
        JSON 结果
    """
    try:
        jobs = _load_cron_jobs()
        
        # 过滤提醒任务
        reminders = []
        for job in jobs:
            if not _is_reminder_job(job):
                continue
            
            # 过滤状态
            if active_only and not job.get("enabled", True):
                continue
            
            # 过滤平台
            if platform and job.get("deliver") != platform:
                continue
            
            reminders.append({
                "job_id": job.get("id", job.get("job_id", "")),
                "content": _extract_content_from_name(job.get("name", "")),
                "schedule": job.get("schedule", {}),
                "repeat": "once" if job.get("repeat", {}).get("times") == 1 else "recurring",
                "platform": job.get("deliver", ""),
                "next_run": job.get("next_run_at", ""),
                "status": "active" if job.get("enabled") else "paused"
            })
        
        # 排序
        reminders.sort(key=lambda r: r.get("next_run", ""))
        
        return json.dumps({
            "success": True,
            "reminders": reminders,
            "count": len(reminders)
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============================================================================
# 核心功能：取消提醒
# ============================================================================

def reminder_cancel(job_id: str) -> str:
    """
    取消提醒
    
    Args:
        job_id: 提醒 ID
    
    Returns:
        JSON 结果
    """
    try:
        # 验证是否为提醒任务
        jobs = _load_cron_jobs()
        target = None
        for job in jobs:
            # job_id 可能在 'id' 或 'job_id' 字段
            if job.get("id") == job_id or job.get("job_id") == job_id:
                target = job
                break
        
        if not target:
            return json.dumps({
                "success": False,
                "error": f"未找到提醒：{job_id}"
            }, ensure_ascii=False)
        
        if not _is_reminder_job(target):
            return json.dumps({
                "success": False,
                "error": "该任务不是提醒任务"
            }, ensure_ascii=False)
        
        # 执行删除
        # job_id 是位置参数，不是 --job-id
        result = _run_hermes_cron(["remove", job_id])
        
        if result["success"]:
            return json.dumps({
                "success": True,
                "message": f"已取消提醒：{_extract_content_from_name(target.get('name', ''))}"
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": result["error"] or "取消失败"
            }, ensure_ascii=False)
            
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============================================================================
# 核心功能：更新提醒
# ============================================================================

def reminder_update(
    job_id: str,
    content: str = None,
    time: str = None,
    repeat: str = None,
    platform: str = None
) -> str:
    """
    更新提醒
    
    Args:
        job_id: 提醒 ID
        content: 新内容（可选）
        time: 新时间（可选）
        repeat: 新重复模式（可选）
        platform: 新平台（可选）
    
    Returns:
        JSON 结果
    """
    try:
        # 查找提醒
        jobs = _load_cron_jobs()
        target = None
        for job in jobs:
            # job_id 可能在 'id' 或 'job_id' 字段
            if job.get("id") == job_id or job.get("job_id") == job_id:
                target = job
                break
        
        if not target:
            return json.dumps({
                "success": False,
                "error": f"未找到提醒：{job_id}"
            }, ensure_ascii=False)
        
        if not _is_reminder_job(target):
            return json.dumps({
                "success": False,
                "error": "该任务不是提醒任务"
            }, ensure_ascii=False)
        
        # 先删除旧的
        _run_hermes_cron(["remove", "--job-id", job_id])
        
        # 使用新参数或保留旧值
        new_content = content or _extract_content_from_name(target.get("name", ""))
        new_time = time or target.get("schedule", "")
        new_repeat = repeat or ("once" if target.get("repeat") == 1 else "daily")
        new_platform = platform or target.get("deliver", "wecom")
        
        # 创建新的
        return reminder_create(new_content, new_time, new_repeat, new_platform)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============================================================================
# 工具注册
# ============================================================================

REMINDER_CREATE_SCHEMA = {
    "name": "reminder_create",
    "description": (
        "【智能提醒】创建提醒任务。调用前必须完成语义推理：\n\n"
        "## 第一步：场景推理（调用前必做）\n"
        "根据事项类型推理最佳提醒时机，不能直接用用户说的时间：\n"
        "- 会议/约会 → 提前15~30分钟\n"
        "- 信用卡还款/账单 → 到期日提前3天\n"
        "- 生日/纪念日 → 提前7天\n"
        "- 抢票/秒杀 → 开售前10分钟\n"
        "- 工作截止 → 提前1天\n"
        "- 日常事务（充电、吃药等）→ 按用户指定时间\n\n"
        "## 第二步：参数规范\n"
        "- content: 纯内容，去除'提醒我'/'别忘了'等前缀\n"
        "- time: 必须是精确 ISO 时间戳（2026-05-24T23:00:00），不能传'今晚'等模糊值\n"
        "- repeat: 一次性用 once，每天/每周/每月用对应值\n"
        "- platform: 用户在哪个平台提问就发哪里（wecom/telegram/feishu）\n\n"
        "## 第三步：信息不足时\n"
        "缺少关键信息时先询问，不要猜测。每次只问一个问题。\n\n"
        "⚠️ 禁止传入模糊时间，禁止跳过场景推理直接调用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "提醒内容（原样发送）"
            },
            "time": {
                "type": "string",
                "description": "提醒时间（ISO 格式或相对时间，如 2026-05-24T23:00:00 或 +30m）"
            },
            "repeat": {
                "type": "string",
                "enum": ["once", "daily", "weekly", "monthly"],
                "description": "重复模式，默认 once",
                "default": "once"
            },
            "platform": {
                "type": "string",
                "enum": ["wecom", "telegram", "feishu"],
                "description": "发送平台，默认 wecom",
                "default": "wecom"
            }
        },
        "required": ["content", "time"]
    }
}

REMINDER_LIST_SCHEMA = {
    "name": "reminder_list",
    "description": "【智能提醒 - 执行层】查询提醒列表。",
    "parameters": {
        "type": "object",
        "properties": {
            "active_only": {
                "type": "boolean",
                "description": "仅显示未完成的提醒，默认 true",
                "default": True
            },
            "platform": {
                "type": "string",
                "description": "过滤平台（可选）"
            }
        },
        "required": []
    }
}

REMINDER_CANCEL_SCHEMA = {
    "name": "reminder_cancel",
    "description": "【智能提醒 - 执行层】取消提醒。",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "提醒 ID"
            }
        },
        "required": ["job_id"]
    }
}

REMINDER_UPDATE_SCHEMA = {
    "name": "reminder_update",
    "description": "【智能提醒 - 执行层】更新提醒。",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "提醒 ID"
            },
            "content": {
                "type": "string",
                "description": "新内容（可选）"
            },
            "time": {
                "type": "string",
                "description": "新时间（可选）"
            },
            "repeat": {
                "type": "string",
                "enum": ["once", "daily", "weekly", "monthly"],
                "description": "新重复模式（可选）"
            },
            "platform": {
                "type": "string",
                "description": "新平台（可选）"
            }
        },
        "required": ["job_id"]
    }
}


# 注册工具
registry.register(
    name="reminder_create",
    toolset="reminder",
    emoji="⏰",
    schema=REMINDER_CREATE_SCHEMA,
    handler=lambda args, **kw: reminder_create(
        args["content"],
        args["time"],
        args.get("repeat", "once"),
        args.get("platform", "wecom")
    )
)

registry.register(
    name="reminder_list",
    toolset="reminder",
    emoji="📋",
    schema=REMINDER_LIST_SCHEMA,
    handler=lambda args, **kw: reminder_list(
        args.get("active_only", True),
        args.get("platform")
    )
)

registry.register(
    name="reminder_cancel",
    toolset="reminder",
    emoji="❌",
    schema=REMINDER_CANCEL_SCHEMA,
    handler=lambda args, **kw: reminder_cancel(args["job_id"])
)

registry.register(
    name="reminder_update",
    toolset="reminder",
    emoji="✏️",
    schema=REMINDER_UPDATE_SCHEMA,
    handler=lambda args, **kw: reminder_update(
        args["job_id"],
        args.get("content"),
        args.get("time"),
        args.get("repeat"),
        args.get("platform")
    )
)


# ============================================================================
# 健康检查与恢复
# ============================================================================

def reminder_health_check() -> str:
    """
    智能提醒工具健康检查
    
    Returns:
        JSON 格式的健康状态报告
    """
    result = {
        "status": "ok",
        "checks": {},
        "version": "1.0.0"
    }
    
    # 1. 检查依赖
    try:
        deps = _check_dependencies()
        result["checks"]["dependencies"] = {
            "status": "ok" if all(deps.values()) else "error",
            "details": deps
        }
        if not all(deps.values()):
            result["status"] = "error"
    except Exception as e:
        result["checks"]["dependencies"] = {"status": "error", "error": str(e)}
        result["status"] = "error"
    
    # 2. 检查数据文件
    try:
        jobs = _load_cron_jobs()
        reminder_count = sum(1 for j in jobs if _is_reminder_job(j))
        result["checks"]["data_file"] = {
            "status": "ok",
            "total_jobs": len(jobs),
            "reminder_count": reminder_count
        }
    except Exception as e:
        result["checks"]["data_file"] = {"status": "error", "error": str(e)}
        result["status"] = "error"
    
    # 3. 检查备份
    backup_dir = os.path.expanduser("~/.hermes/backups/smart-reminder")
    if os.path.exists(backup_dir):
        backups = [f for f in os.listdir(backup_dir) if f.endswith(".py")]
        result["checks"]["backup"] = {
            "status": "ok",
            "latest_backup": max(backups) if backups else None
        }
    else:
        result["checks"]["backup"] = {"status": "warning", "message": "无备份"}
    
    return json.dumps(result, ensure_ascii=False, indent=2)


def reminder_self_test() -> str:
    """
    自检测试
    
    Returns:
        JSON 格式的测试结果
    """
    results = []
    
    # 测试 1: 创建提醒
    try:
        result = reminder_create(
            content="[自检测试] 请忽略",
            time="2099-12-31T23:59:59",
            repeat="once",
            platform="wecom"
        )
        data = json.loads(result)
        job_id = data.get("job_id")
        
        if data.get("success"):
            results.append({"test": "create", "status": "pass"})
            
            # 测试 2: 查询列表
            result = reminder_list()
            data = json.loads(result)
            if data.get("success"):
                results.append({"test": "list", "status": "pass"})
            else:
                results.append({"test": "list", "status": "fail", "error": data.get("error")})
            
            # 测试 3: 取消提醒
            result = reminder_cancel(job_id)
            data = json.loads(result)
            if data.get("success"):
                results.append({"test": "cancel", "status": "pass"})
            else:
                results.append({"test": "cancel", "status": "fail", "error": data.get("error")})
        else:
            results.append({"test": "create", "status": "fail", "error": data.get("error")})
    except Exception as e:
        results.append({"test": "create", "status": "error", "error": str(e)})
    
    passed = sum(1 for r in results if r["status"] == "pass")
    total = len(results)
    
    return json.dumps({
        "success": passed == total,
        "passed": passed,
        "total": total,
        "results": results
    }, ensure_ascii=False, indent=2)
