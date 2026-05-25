"""Dedicated workflow-closure validation for the real completion hook path."""

from unittest.mock import patch

from hermes_state import SessionDB


def test_maybe_complete_workflow_task_marks_open_session(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("sess_open", "telegram")

        assert db.maybe_complete_workflow_task("sess_open", reason="completed") is True

        row = db.get_session("sess_open")
        assert row["ended_at"] is not None
        assert row["end_reason"] == "completed"
    finally:
        db.close()


def test_maybe_complete_workflow_task_is_best_effort_on_failure(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("sess_fail", "telegram")

        with patch.object(db, "advance_session_state", side_effect=RuntimeError("boom")):
            assert db.maybe_complete_workflow_task("sess_fail") is False

        row = db.get_session("sess_fail")
        assert row["ended_at"] is None
        assert row["end_reason"] is None
    finally:
        db.close()


def test_maybe_complete_workflow_task_noops_for_unknown_session(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        assert db.maybe_complete_workflow_task("missing-session") is False
    finally:
        db.close()


def test_maybe_complete_workflow_task_rejects_unknown_reason(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("sess_reason", "telegram")

        assert db.maybe_complete_workflow_task("sess_reason", reason="unexpected") is False

        row = db.get_session("sess_reason")
        assert row["ended_at"] is None
        assert row["end_reason"] is None
    finally:
        db.close()
