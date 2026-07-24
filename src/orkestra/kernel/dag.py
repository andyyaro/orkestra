"""Task dependency graph: validation, cycle detection, ready frontier.

A ~100-line replacement for a graph library (ADR: TECH_STACK_DECISION
decision 5). Keys are task keys; the persisted relational form lives in
``task_deps``.
"""

from __future__ import annotations

from collections import deque

from orkestra.errors import DagError
from orkestra.schemas.common import TaskState

_UNFINISHED = {
    TaskState.PENDING,
    TaskState.READY,
    TaskState.RUNNING,
    TaskState.VERIFYING,
    TaskState.REVIEWING,
    TaskState.INTEGRATING,
    TaskState.BLOCKED,
}


class TaskDag:
    """Immutable dependency graph over task keys."""

    def __init__(self, deps: dict[str, list[str]], all_keys: list[str]) -> None:
        self.keys = list(all_keys)
        key_set = set(self.keys)
        if len(key_set) != len(self.keys):
            msg = "duplicate task keys in graph"
            raise DagError(msg)
        self.deps: dict[str, list[str]] = {k: sorted(set(deps.get(k, []))) for k in self.keys}
        for key, dependencies in self.deps.items():
            for dep in dependencies:
                if dep not in key_set:
                    msg = f"task {key!r} depends on unknown task {dep!r}"
                    raise DagError(msg)
                if dep == key:
                    msg = f"task {key!r} depends on itself"
                    raise DagError(msg)
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        """Kahn's algorithm; leftover nodes mean a cycle."""
        indegree = {k: len(self.deps[k]) for k in self.keys}
        dependents: dict[str, list[str]] = {k: [] for k in self.keys}
        for key, dependencies in self.deps.items():
            for dep in dependencies:
                dependents[dep].append(key)
        queue = deque(k for k, d in indegree.items() if d == 0)
        seen = 0
        while queue:
            node = queue.popleft()
            seen += 1
            for dependent in dependents[node]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        if seen != len(self.keys):
            cycle_members = sorted(k for k, d in indegree.items() if d > 0)
            msg = f"task graph contains a cycle involving: {', '.join(cycle_members)}"
            raise DagError(msg)

    def topological_order(self) -> list[str]:
        indegree = {k: len(self.deps[k]) for k in self.keys}
        dependents: dict[str, list[str]] = {k: [] for k in self.keys}
        for key, dependencies in self.deps.items():
            for dep in dependencies:
                dependents[dep].append(key)
        queue = deque(sorted(k for k, d in indegree.items() if d == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for dependent in sorted(dependents[node]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        return order

    def ready_keys(self, states: dict[str, TaskState]) -> list[str]:
        """Tasks whose dependencies are DONE and which are still PENDING/READY."""
        ready: list[str] = []
        for key in self.keys:
            state = states.get(key, TaskState.PENDING)
            if state not in (TaskState.PENDING, TaskState.READY):
                continue
            if all(states.get(dep) == TaskState.DONE for dep in self.deps[key]):
                ready.append(key)
        return ready

    def downstream_of(self, key: str) -> set[str]:
        """All tasks that (transitively) depend on *key*."""
        dependents: dict[str, list[str]] = {k: [] for k in self.keys}
        for k, dependencies in self.deps.items():
            for dep in dependencies:
                dependents[dep].append(k)
        result: set[str] = set()
        queue = deque(dependents[key])
        while queue:
            node = queue.popleft()
            if node in result:
                continue
            result.add(node)
            queue.extend(dependents[node])
        return result

    def is_complete(self, states: dict[str, TaskState]) -> bool:
        return all(states.get(k) == TaskState.DONE for k in self.keys)

    def is_stuck(self, states: dict[str, TaskState]) -> bool:
        """True when nothing can ever become ready again."""
        if self.ready_keys(states):
            return False
        active = {
            TaskState.RUNNING,
            TaskState.VERIFYING,
            TaskState.REVIEWING,
            TaskState.INTEGRATING,
        }
        if any(states.get(k) in active for k in self.keys):
            return False
        return not self.is_complete(states)
