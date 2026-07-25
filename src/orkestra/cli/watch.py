"""`orkestra watch` — a Textual monitor over the run state store.

Read-mostly by design: it observes the same SQLite database the kernel
writes (safe from any process) and exposes only the pause/cancel
control flags. It never dispatches work — the CLI `run`/`resume`
commands own execution. Textual is an optional dependency
(`pip install "orkestra-runtime[tui]"`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App as TextualApp
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

if TYPE_CHECKING:
    from orkestra.app import App as OrkestraApp

_STATE_STYLE = {
    "done": "green",
    "failed": "red",
    "blocked": "yellow",
    "cancelled": "dim",
    "running": "cyan",
    "verifying": "cyan",
    "reviewing": "magenta",
    "integrating": "magenta",
}


class WatchApp(TextualApp[None]):
    """Live monitor for one Orkestra run."""

    TITLE = "orkestra watch"
    CSS = """
    #summary { height: 3; padding: 0 1; background: $surface; }
    #tasks { height: 1fr; }
    #decisions { height: auto; max-height: 8; padding: 0 1;
                 background: $surface; color: $warning; }
    #events { height: 12; border-top: solid $primary; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "pause", "Request pause"),
        Binding("c", "cancel", "Request cancel"),
    ]

    def __init__(self, application: OrkestraApp, run_id: str) -> None:
        super().__init__()
        self.application = application
        self.run_id = run_id
        self._last_event_id = 0

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static(id="summary")
            with Horizontal():
                yield DataTable[str](id="tasks")
            yield Static(id="decisions")
            yield RichLog(id="events", wrap=True, markup=False, max_lines=500)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tasks", DataTable)
        table.add_columns("task", "kind", "state", "primary", "reviewers", "attempts")
        table.cursor_type = "row"
        self.refresh_state()
        self.set_interval(1.0, self.refresh_state)

    # ----------------------------------------------------------- refresh

    def refresh_state(self) -> None:
        store = self.application.store
        run = store.get_run(self.run_id)
        summary = self.query_one("#summary", Static)
        summary.update(
            f"run [b]{run.run_id}[/b] · project {run.project_name} · state "
            f"[b]{run.state.value}[/b] · integration {run.integration_branch or '—'}"
        )

        table = self.query_one("#tasks", DataTable)
        table.clear()
        for task in store.tasks_for_run(self.run_id):
            style = _STATE_STYLE.get(task.state.value, "")
            state_cell = f"[{style}]{task.state.value}[/{style}]" if style else task.state.value
            assignment = task.assignment
            table.add_row(
                task.key,
                task.spec.kind.value,
                state_cell,
                assignment.primary if assignment else "—",
                ", ".join(assignment.reviewers) if assignment else "—",
                str(task.attempt_count),
                key=task.task_id,
            )

        open_decisions = store.decisions_for_run(self.run_id, unresolved_only=True)
        decisions = self.query_one("#decisions", Static)
        if open_decisions:
            lines = [
                f"⚠ {d.decision_id}: {d.question[:110]}  →  "
                f"orkestra approve {d.decision_id} --option <key>"
                for d in open_decisions
            ]
            decisions.update("\n".join(lines))
        else:
            decisions.update("")

        log = self.query_one("#events", RichLog)
        for event in store.events_for_run(self.run_id, limit=100):
            if event["event_id"] <= self._last_event_id:
                continue
            self._last_event_id = event["event_id"]
            text = str(event["text"]).replace("\n", " ")[:200]
            if text:
                log.write(f"{event['ts'][11:19]} {event['kind']:>9}  {text}")

    # ------------------------------------------------------------ actions

    def action_pause(self) -> None:
        self.application.orchestrator.request_pause(self.run_id)
        self.notify("pause requested (in-flight tasks will finish)")

    def action_cancel(self) -> None:
        self.application.orchestrator.request_cancel(self.run_id)
        self.notify("cancel requested", severity="warning")
