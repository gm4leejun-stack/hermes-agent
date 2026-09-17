#!/usr/bin/env python3
"""Minimal enforceable project-management workflow state store.

This module is intentionally small and opinionated:
- JSON state stored in ~/.hermes/projects/workflow.json
- append-only event log stored in ~/.hermes/projects/logs/workflow-events.jsonl
- atomic writes for all state mutations
- simple state-machine enforcement for projects, milestones, and tasks
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ALLOWED_PROJECT_STATES = {"planned", "active", "blocked", "completed", "canceled"}
ALLOWED_TASK_STATES = {"todo", "doing", "blocked", "review", "done", "canceled"}
ALLOWED_ALL_STATES = ALLOWED_PROJECT_STATES | ALLOWED_TASK_STATES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


def _projects_dir() -> Path:
    return _hermes_home() / "projects"


def _logs_dir() -> Path:
    return _projects_dir() / "logs"


def _state_path() -> Path:
    return _projects_dir() / "workflow.json"


def _schema_path() -> Path:
    return _projects_dir() / "workflow.schema.json"


def _event_log_path() -> Path:
    return _logs_dir() / "workflow-events.jsonl"


def ensure_dirs() -> None:
    _projects_dir().mkdir(parents=True, exist_ok=True)
    _logs_dir().mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_projects_dir(), 0o700)
        os.chmod(_logs_dir(), 0o700)
    except OSError:
        pass


def default_state() -> Dict[str, Any]:
    return {"version": 1, "updated_at": _now(), "projects": []}


def load_state() -> Dict[str, Any]:
    ensure_dirs()
    path = _state_path()
    if not path.exists():
        return default_state()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dirs()
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_event(event: Dict[str, Any]) -> None:
    ensure_dirs()
    with open(_event_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True))
        f.write("\n")


def _find_project(state: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    for project in state.get("projects", []):
        if project.get("id") == project_id:
            return project
    raise KeyError(f"project not found: {project_id}")


def _find_milestone(project: Dict[str, Any], milestone_id: str) -> Dict[str, Any]:
    for milestone in project.get("milestones", []):
        if milestone.get("id") == milestone_id:
            return milestone
    raise KeyError(f"milestone not found: {milestone_id}")


def _find_task(milestone: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    for task in milestone.get("tasks", []):
        if task.get("id") == task_id:
            return task
    raise KeyError(f"task not found: {task_id}")


def _task_lookup(state: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for project in state.get("projects", []):
        for milestone in project.get("milestones", []):
            for task in milestone.get("tasks", []):
                if task.get("id") == task_id:
                    return task
    return None


def _dependencies_done(state: Dict[str, Any], depends_on: Iterable[str]) -> bool:
    for dep_id in depends_on:
        dep = _task_lookup(state, dep_id)
        if not dep or dep.get("state") != "done":
            return False
    return True


def _validate_completion(state: Dict[str, Any], project: Dict[str, Any]) -> None:
    for milestone in project.get("milestones", []):
        for task in milestone.get("tasks", []):
            if task.get("state") not in {"done", "canceled"}:
                raise ValueError("project cannot be completed until all tasks are done or canceled")
        if milestone.get("state") not in {"done", "completed"}:
            raise ValueError("project cannot be completed until all milestones are complete")


def _task_priority_value(task: Dict[str, Any]) -> int:
    priority = str(task.get("priority", "medium")).lower()
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get(priority, 1)


def _task_sort_key(task: Dict[str, Any]) -> Tuple[int, str, str]:
    return (
        _task_priority_value(task),
        str(task.get("updated_at") or task.get("created_at") or ""),
        str(task.get("id") or ""),
    )


def _normalize_task(task: Dict[str, Any], project: Dict[str, Any], milestone: Dict[str, Any]) -> Dict[str, Any]:
    task_copy = dict(task)
    task_copy["project_id"] = project.get("id")
    task_copy["project_name"] = project.get("name")
    task_copy["milestone_id"] = milestone.get("id")
    task_copy["milestone_name"] = milestone.get("name")
    return task_copy


def _iter_candidate_tasks(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for project in state.get("projects", []):
        if not isinstance(project, dict) or project.get("state") not in {"planned", "active", "blocked"}:
            continue
        for milestone in project.get("milestones", []):
            if not isinstance(milestone, dict) or milestone.get("state") in {"done", "completed", "canceled"}:
                continue
            for task in milestone.get("tasks", []):
                if not isinstance(task, dict) or task.get("state") not in {"todo", "doing", "blocked", "review"}:
                    continue
                candidates.append(_normalize_task(task, project, milestone))
    candidates.sort(key=_task_sort_key)
    return candidates


def _task_feedback(task: Dict[str, Any], event_type: str) -> str:
    priority = str(task.get("priority", "medium")).lower()
    return f"{event_type}: {task.get('id')} [{priority}] {task.get('title', '')}"


def get_next_task(state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    state = state or load_state()
    candidates = _iter_candidate_tasks(state)
    return candidates[0] if candidates else None


def promote_next_task(state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return get_next_task(state)


def get_current_priority(state: Optional[Dict[str, Any]] = None) -> Optional[str]:
    next_task = get_next_task(state)
    return None if not next_task else str(next_task.get("priority", "medium"))


def _update_milestone_state(milestone: Dict[str, Any]) -> None:
    if milestone.get("tasks") and all(t.get("state") in {"done", "canceled"} for t in milestone.get("tasks", [])):
        milestone["state"] = "done"


def create_project(project_id: str, name: str, goal: str, owner: str, definition_of_done: List[str]) -> Dict[str, Any]:
    state = load_state()
    if any(p.get("id") == project_id for p in state.get("projects", [])):
        raise ValueError(f"project already exists: {project_id}")
    project = {
        "id": project_id,
        "name": name,
        "goal": goal,
        "state": "planned",
        "created_at": _now(),
        "updated_at": _now(),
        "owner": owner,
        "definition_of_done": list(definition_of_done),
        "milestones": [],
    }
    state["projects"].append(project)
    state["updated_at"] = _now()
    _atomic_write_json(_state_path(), state)
    _append_event({"type": "project.created", "project_id": project_id, "at": _now()})
    return project


def add_milestone(project_id: str, milestone_id: str, name: str) -> Dict[str, Any]:
    state = load_state()
    project = _find_project(state, project_id)
    milestone = {"id": milestone_id, "name": name, "state": "todo", "tasks": []}
    project["milestones"].append(milestone)
    project["updated_at"] = _now()
    state["updated_at"] = _now()
    _atomic_write_json(_state_path(), state)
    _append_event({"type": "milestone.created", "project_id": project_id, "milestone_id": milestone_id, "at": _now()})
    return milestone


def add_task(project_id: str, milestone_id: str, task_id: str, title: str, depends_on: Optional[List[str]] = None) -> Dict[str, Any]:
    state = load_state()
    project = _find_project(state, project_id)
    milestone = _find_milestone(project, milestone_id)
    task = {
        "id": task_id,
        "title": title,
        "state": "todo",
        "created_at": _now(),
        "updated_at": _now(),
        "blocked_reason": None,
        "depends_on": list(depends_on or []),
        "notes": [],
    }
    milestone["tasks"].append(task)
    project["updated_at"] = _now()
    state["updated_at"] = _now()
    _atomic_write_json(_state_path(), state)
    _append_event({"type": "task.created", "project_id": project_id, "milestone_id": milestone_id, "task_id": task_id, "at": _now()})
    return task


def set_task_state(project_id: str, milestone_id: str, task_id: str, state_name: str, note: Optional[str] = None, blocked_reason: Optional[str] = None) -> Dict[str, Any]:
    if state_name not in ALLOWED_TASK_STATES:
        raise ValueError(f"invalid task state: {state_name}")
    state = load_state()
    project = _find_project(state, project_id)
    milestone = _find_milestone(project, milestone_id)
    task = _find_task(milestone, task_id)
    if state_name == "done" and not _dependencies_done(state, task.get("depends_on", [])):
        raise ValueError("task dependencies are not complete")
    task["state"] = state_name
    task["blocked_reason"] = blocked_reason if state_name == "blocked" else None
    task["updated_at"] = _now()
    if note:
        task.setdefault("notes", []).append(note)
    _update_milestone_state(milestone)
    project["updated_at"] = _now()
    state["updated_at"] = _now()
    _atomic_write_json(_state_path(), state)
    _append_event({"type": "task.state_changed", "project_id": project_id, "milestone_id": milestone_id, "task_id": task_id, "state": state_name, "at": _now()})
    return task


def complete_task(project_id: str, milestone_id: str, task_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Mark a task done and return the updated task."""
    task = set_task_state(project_id, milestone_id, task_id, "done", note=note)
    task["completion_feedback"] = _task_feedback(task, "completed")
    return task


def set_project_state(project_id: str, state_name: str) -> Dict[str, Any]:
    if state_name not in ALLOWED_PROJECT_STATES:
        raise ValueError(f"invalid project state: {state_name}")
    state = load_state()
    project = _find_project(state, project_id)
    if state_name == "completed":
        _validate_completion(state, project)
    project["state"] = state_name
    project["updated_at"] = _now()
    state["updated_at"] = _now()
    _atomic_write_json(_state_path(), state)
    _append_event({"type": "project.state_changed", "project_id": project_id, "state": state_name, "at": _now()})
    return project


def complete_task_and_promote_next(project_id: str, milestone_id: str, task_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Complete a task, then return the next promoted task context."""
    complete_task(project_id, milestone_id, task_id, note=note)
    refreshed = load_state()
    next_task = get_next_task(refreshed)
    return {
        "completed_task_id": task_id,
        "completed_feedback": f"completed: {task_id}",
        "next_task": next_task,
        "current_priority": None if not next_task else next_task.get("priority", "medium"),
    }


def snapshot() -> Dict[str, Any]:
    return load_state()
