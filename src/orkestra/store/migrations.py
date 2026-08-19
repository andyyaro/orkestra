"""Linear, auditable schema migration chain.

Each entry runs inside one transaction; ``schema_version`` records the
applied chain position. Never edit an applied migration - append a new
one.
"""

from __future__ import annotations

MIGRATIONS: list[str] = [
    # 0001 - initial schema
    """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        state TEXT NOT NULL,
        base_commit TEXT NOT NULL DEFAULT '',
        integration_branch TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        key TEXT NOT NULL,
        state TEXT NOT NULL,
        kind TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        review_cycles INTEGER NOT NULL DEFAULT 0,
        payload TEXT NOT NULL,
        assignment TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL,
        UNIQUE (run_id, key)
    );
    CREATE INDEX idx_tasks_run_state ON tasks(run_id, state);

    CREATE TABLE task_deps (
        run_id TEXT NOT NULL,
        task_key TEXT NOT NULL,
        depends_on_key TEXT NOT NULL,
        PRIMARY KEY (run_id, task_key, depends_on_key)
    );

    CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        run_id TEXT NOT NULL,
        agent TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'primary',
        state TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        result TEXT,
        workspace TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_attempts_task ON attempts(task_id);
    CREATE INDEX idx_attempts_run_state ON attempts(run_id, state);

    CREATE TABLE events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        task_id TEXT,
        attempt_id TEXT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_events_run ON events(run_id, event_id);
    CREATE INDEX idx_events_attempt ON events(attempt_id);

    CREATE TABLE decisions (
        decision_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        resolved INTEGER NOT NULL DEFAULT 0,
        payload TEXT NOT NULL
    );

    CREATE TABLE observations (
        observation_id TEXT PRIMARY KEY,
        agent TEXT NOT NULL,
        agent_version TEXT NOT NULL DEFAULT '',
        capability TEXT NOT NULL,
        source TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_observations_agent ON observations(agent, capability);

    CREATE TABLE ledger (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        agent TEXT NOT NULL,
        task_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        outcome TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_ledger_agent ON ledger(agent);

    CREATE TABLE workspaces (
        workspace_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        path TEXT NOT NULL,
        branch TEXT NOT NULL,
        base_commit TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL
    );

    CREATE TABLE usage_log (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        agent TEXT NOT NULL,
        attempt_id TEXT,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        total_cost_usd REAL,
        created_at TEXT NOT NULL
    );
    """,
    # v0.5.0: cache-read/creation tokens are most of a coding agent's real
    # input volume; without them the usage table understates input wildly.
    """
    ALTER TABLE usage_log ADD COLUMN cached_input_tokens INTEGER NOT NULL DEFAULT 0;
    """,
]
