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
    # A verification result used to exist only as rendered event prose, so its
    # duration, environment and the tree it ran against could not be queried,
    # audited or compared later. One row per gate command actually executed.
    # Both a commit sha and a tree sha are stored: the tree sha names the
    # committed tree HEAD pointed at, the commit sha is what an audit verb can
    # check out ("git checkout <tree>" does not work). The tree sha describes
    # what the gate READ only when tree_clean is 1: verification runs on every
    # task while only a mutating task commits first, so a research or review
    # task is gated over a dirty worktree. dirty_digest fingerprints what
    # differed, so an audit can report CANNOT-CHECK rather than agreeing with
    # a row whose tree is not the tree that ran.
    """
    CREATE TABLE verifications (
        verification_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT,
        scope TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        tree_sha TEXT NOT NULL,
        tree_clean INTEGER NOT NULL,
        dirty_digest TEXT NOT NULL,
        attempt_id TEXT,
        command TEXT NOT NULL,
        argv_json TEXT NOT NULL,
        exe_realpath TEXT,
        exe_version TEXT,
        env_fingerprint TEXT NOT NULL,
        exit_code INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        output_digest TEXT,
        binding TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_verifications_run ON verifications(run_id);
    CREATE INDEX idx_verifications_task ON verifications(task_id);
    """,
    # A binding verdict is a property of the gate and the environment, not of
    # the tree: it was identical across three different trees of one repo and
    # flipped only when the environment changed. Proving it costs two extra
    # gate runs, which is why it was opt-in; cached on that identity it is paid
    # once per configuration instead of once per run, which is what lets it be
    # on by default.
    """
    CREATE TABLE binding_proofs (
        cache_key TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        reason TEXT NOT NULL,
        commands_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]
