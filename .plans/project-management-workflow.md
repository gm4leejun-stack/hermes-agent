# Hermes Project Management Workflow

This artifact is the minimal enforceable project-management layer for Hermes. It is intentionally small, concrete, and stateful: one JSON state file, one schema, one workflow file, and one Python module that mutates state atomically.

Purpose
- Track initiatives, milestones, and tasks.
- Enforce visible state transitions so work can be audited and resumed.
- Provide a machine-readable artifact that agents can consume directly.

Core artifacts
- State file: ~/.hermes/projects/workflow.json
- Workflow contract: ~/.hermes/projects/workflow.schema.json
- Control module: ~/.hermes/projects/workflow.py
- Canonical execution log: ~/.hermes/projects/logs/workflow-events.jsonl

Loader contract
- The loader should accept a missing state file by creating the default v1 shape.
- The root object must contain version, updated_at, and projects.
- Unknown top-level or nested fields should be preserved by consumers that rewrite state.
- Consumers should treat timestamps as opaque ISO-8601 strings.

Minimal operating model
1. Create a project with a goal, owner, and definition of done.
2. Break it into milestones and tasks.
3. Move tasks through allowed states only.
4. Record every mutation as an append-only event.
5. Consider the project done only when all milestones are complete and definition of done is met.

Allowed task states
- todo
- doing
- blocked
- review
- done
- canceled

Allowed project states
- planned
- active
- blocked
- completed
- canceled

Required fields
Project:
- id
- name
- goal
- state
- created_at
- updated_at
- owner
- definition_of_done
- milestones

Milestone:
- id
- name
- state
- tasks

Task:
- id
- title
- state
- created_at
- updated_at
- blocked_reason
- depends_on
- notes

Enforcement rules
- Every update must preserve schema validity.
- A task cannot move to done unless all dependencies are done.
- A project cannot move to completed unless every milestone is completed and every task is done or canceled.
- State changes must be appended to the event log.
- Unknown fields are preserved to avoid data loss, but required fields must exist.
- The module must write via temp-file + atomic rename.

Integration notes
- If a startup hook needs a stable handoff target, use the root PROJECT_CONTINUITY_STATE.yaml as the operator-facing pointer and this workflow as the machine state store.
- If a loader is added, it should prefer existing state, fall back to default_state(), and avoid silently rewriting unknown fields away.

This is the smallest artifact that is still enforceable: it is both documentation and an executable state machine entrypoint.
