# ADR-0003: Persistence — SQLite (WAL) with plain SQL and versioned JSON payloads

Date: 2026-07-24 · Status: accepted

## Context

State must survive process interruption, terminal closure, crashes, and
machine restarts, with transactional idempotent transitions and an
append-only event log. The provisional stack suggested SQLAlchemy 2 +
Alembic.

## Decision

Use stdlib `sqlite3` in WAL mode with:

- explicit, parameterized SQL in a small repository layer;
- narrow relational columns for identity/state/indexes, plus a JSON
  `payload` column per entity validated by versioned Pydantic models;
- a linear migration chain of numbered SQL scripts tracked in a
  `schema_version` table (applied transactionally at open).

## Rationale

- ~15 tables and one writer do not justify SQLAlchemy + Alembic
  (two large dependencies, slower cold start, magic in migrations).
- Auditable SQL matches the security posture (SQL injection is
  structurally prevented by parameterization; the diff of a migration
  script is reviewable).
- Pydantic-versioned payloads give schema evolution for rich documents
  without ORM churn.

## Consequences

- Joins/queries are hand-written; acceptable at this scale.
- A future multi-process mode would need a write-lock discipline —
  documented as out of scope for v0.1 (single kernel process holds an
  advisory lock file).
