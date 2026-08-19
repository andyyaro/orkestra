"""Final report generation (markdown + machine-readable JSON)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from orkestra.redact import redact
from orkestra.schemas.common import utc_now

if TYPE_CHECKING:
    from orkestra.store import Store


def build_report(store: Store, run_id: str) -> dict[str, Any]:
    """Collect everything known about a run into one JSON-safe document."""
    run = store.get_run(run_id)
    tasks = store.tasks_for_run(run_id)
    report: dict[str, Any] = {
        "generated_at": utc_now().isoformat(),
        "run": {
            "run_id": run.run_id,
            "project": run.project_name,
            "state": run.state.value,
            "base_commit": run.base_commit,
            "integration_branch": run.integration_branch,
            "agents": run.payload.get("agents", {}),
            "analysis": run.payload.get("analysis"),
            "plan_notes": run.payload.get("plan_notes", ""),
            "challenges": run.payload.get("challenges", []),
            "capability_matrix": run.payload.get("matrix"),
        },
        "tasks": [],
        "decisions": [d.model_dump(mode="json") for d in store.decisions_for_run(run_id)],
        "usage": store.usage_summary(run_id),
        "usage_total": _usage_total(store.usage_summary(run_id)),
        "agent_performance": store.ledger_summary(),
        "field_notes": {
            "attempts[].state": (
                "outcome of the agent call itself (process ran and returned a "
                "result), not whether the task passed verification or review; "
                "task outcomes live in agent_performance and task.state"
            ),
            "usage": (
                "covers every LLM call including director analysis, planning, "
                "plan challenges and capability probes; cost is reported only "
                "by agents that expose it"
            ),
        },
    }
    for task in tasks:
        attempts = store.attempts_for_task(task.task_id)
        report["tasks"].append(
            {
                "task_id": task.task_id,
                "key": task.key,
                "title": task.spec.title,
                "kind": task.spec.kind.value,
                "state": task.state.value,
                "depends_on": task.spec.depends_on,
                "assignment": task.assignment.model_dump(mode="json") if task.assignment else None,
                # Counters on the task row are budget windows (reset by a
                # human 'retry'); the report shows true history from the
                # attempt rows instead.
                "attempt_count": sum(1 for a in attempts if a.role == "primary"),
                "reviews_run": sum(1 for a in attempts if a.role == "reviewer"),
                "review_cycles": task.review_cycles,
                "attempts": [
                    {
                        "attempt_id": a.attempt_id,
                        "agent": a.agent,
                        "role": a.role,
                        # NB: this is the agent call's own outcome (did the
                        # CLI run and return a result), NOT whether the task
                        # passed verification/review - see agent_performance.
                        "agent_call_state": a.state.value,
                        "state": a.state.value,
                        "session_id": (
                            a.result.session.session_id if a.result and a.result.session else None
                        ),
                        "error": (a.result.error_detail[:300] if a.result else ""),
                    }
                    for a in attempts
                ],
            }
        )
    return report


def _usage_total(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Same totals the markdown table prints, for machine consumers."""
    costs = [r["total_cost_usd"] for r in rows if r.get("total_cost_usd") is not None]
    return {
        "calls": sum(r["calls"] for r in rows),
        "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
        "cached_input_tokens": sum(r.get("cached_input_tokens") or 0 for r in rows),
        "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
        "total_cost_usd": round(sum(costs), 4) if costs else None,
        "agents_reporting_cost": len(costs),
        "agents_total": len(rows),
    }


_TAGLIKE = __import__("re").compile(r"</?(?:parameter|item|summary|invoke|function[^>]*)\b[^>]*>")


def _clean_text(text: str, limit: int) -> str:
    """Strip tool-call scaffolding a model may leak into a text field, and
    truncate at a word boundary with an explicit ellipsis."""
    cleaned = _TAGLIKE.sub(" ", text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[:limit]
    cut = head.rfind(" ")
    return (head[:cut] if cut > limit // 2 else head).rstrip(" .,;:") + " … (truncated)"


def render_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    lines = [
        f"# Orkestra Run Report - {run['project']}",
        "",
        f"- **Run:** `{run['run_id']}`  ",
        f"- **State:** **{run['state']}**  ",
        f"- **Base commit:** `{run['base_commit'][:12]}`  ",
        f"- **Integration branch:** `{run['integration_branch']}`  ",
        f"- **Generated:** {report['generated_at']}",
        "",
        "## Agents",
        "",
        "| Agent | Adapter | Version | Available | Auth |",
        "|---|---|---|---|---|",
    ]
    for name, info in (run.get("agents") or {}).items():
        lines.append(
            f"| {name} | {info.get('adapter', '')} | {info.get('version', '')} "
            f"| {info.get('available', '')} | {info.get('auth_ready', '')} |"
        )
    analysis = run.get("analysis")
    if analysis:
        lines += [
            "",
            "## Director analysis",
            "",
            _clean_text(str(analysis.get("summary", "")), 2000),
        ]
        if analysis.get("assumptions"):
            lines += [
                "",
                "Assumptions:",
                *[f"- {_clean_text(str(a), 300)}" for a in analysis["assumptions"][:10]],
            ]
        if analysis.get("risks"):
            lines += [
                "",
                "Risks:",
                *[f"- {_clean_text(str(r), 300)}" for r in analysis["risks"][:10]],
            ]
    lines += [
        "",
        "## Tasks",
        "",
        "| Task | Kind | State | Primary | Reviewers | Attempts | Reviews run | Rejections |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for task in report["tasks"]:
        assignment = task.get("assignment") or {}
        lines.append(
            f"| {task['key']} | {task['kind']} | {task['state']} "
            f"| {assignment.get('primary', '')} "
            f"| {', '.join(assignment.get('reviewers', []))} "
            f"| {task['attempt_count']} | {task.get('reviews_run', 0)} "
            f"| {task['review_cycles']} |"
        )
    if report["decisions"]:
        lines += ["", "## Human decisions", ""]
        for decision in report["decisions"]:
            status = (
                f"resolved: {decision['chosen_option']}"
                if decision.get("chosen_option")
                else "OPEN"
            )
            lines.append(f"- `{decision['decision_id']}` ({status}) - {decision['question'][:200]}")
    if report["usage"]:
        lines += [
            "",
            "## Usage",
            "",
            "| Agent | Calls | Input tokens | Cached input | Output tokens | Cost (USD) |",
            "|---|---|---|---|---|---|",
        ]
        totals = {"calls": 0, "input": 0, "cached": 0, "output": 0, "cost": 0.0}
        any_cost = False
        for row in report["usage"]:
            cost = row.get("total_cost_usd")
            cached = row.get("cached_input_tokens") or 0
            lines.append(
                f"| {row['agent']} | {row['calls']} | {row['input_tokens']} "
                f"| {cached} | {row['output_tokens']} "
                f"| {f'{cost:.4f}' if cost is not None else '-'} |"
            )
            totals["calls"] += row["calls"]
            totals["input"] += row["input_tokens"] or 0
            totals["cached"] += cached
            totals["output"] += row["output_tokens"] or 0
            if cost is not None:
                totals["cost"] += round(cost, 4)
                any_cost = True
        lines.append(
            f"| **total** | {totals['calls']} | {totals['input']} | {totals['cached']} "
            f"| {totals['output']} | "
            f"{f'{totals["cost"]:.4f}' if any_cost else '-'} |"
        )
        if not any_cost or len([r for r in report["usage"] if r.get("total_cost_usd")]) < len(
            report["usage"]
        ):
            lines.append("")
            lines.append(
                "_Cost covers only agents that report it; token columns cover "
                "every call, including planning, challenges, and probes._"
            )
    if report["agent_performance"]:
        lines += [
            "",
            "## Agent performance ledger",
            "",
            "| Agent | Task kind | Outcome | Count |",
            "|---|---|---|---|",
        ]
        for row in report["agent_performance"]:
            lines.append(f"| {row['agent']} | {row['kind']} | {row['outcome']} | {row['n']} |")
    return redact("\n".join(lines) + "\n")


def render_json(report: dict[str, Any]) -> str:
    return redact(json.dumps(report, indent=2, default=str))
