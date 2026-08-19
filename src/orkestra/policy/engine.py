"""Deterministic policy evaluation.

Every dispatch, review pairing, integration, and diff is checked here.
The director can only *propose*; this module (called by the kernel)
disposes. Violations are recorded, never silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from orkestra.schemas.config import PolicyConfig
from orkestra.schemas.task import Assignment


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    violations: list[str] = field(default_factory=list)

    @staticmethod
    def ok() -> PolicyDecision:
        return PolicyDecision(allowed=True)

    @staticmethod
    def deny(*violations: str) -> PolicyDecision:
        return PolicyDecision(allowed=False, violations=list(violations))


class PolicyEngine:
    def __init__(self, config: PolicyConfig, enabled_agents: list[str]) -> None:
        self.config = config
        self.enabled_agents = set(enabled_agents)

    # -------------------------------------------------------- dispatch

    def check_assignment(self, assignment: Assignment) -> PolicyDecision:
        violations: list[str] = []
        if assignment.primary not in self.enabled_agents:
            violations.append(f"primary agent {assignment.primary!r} is not an enabled agent")
        for reviewer in assignment.reviewers:
            if reviewer not in self.enabled_agents:
                violations.append(f"reviewer {reviewer!r} is not an enabled agent")
            if reviewer == assignment.primary:
                violations.append(
                    f"reviewer {reviewer!r} equals the implementer - independent "
                    "review requires primary != reviewer"
                )
        for fallback in assignment.fallbacks:
            if fallback not in self.enabled_agents:
                violations.append(f"fallback {fallback!r} is not an enabled agent")
        if self.config.require_review and not assignment.reviewers:
            violations.append("policy requires at least one independent reviewer")
        if violations:
            return PolicyDecision.deny(*violations)
        return PolicyDecision.ok()

    def check_reviewer(self, implementer: str, reviewer: str) -> PolicyDecision:
        if implementer == reviewer:
            return PolicyDecision.deny(f"agent {reviewer!r} cannot review its own implementation")
        if reviewer not in self.enabled_agents:
            return PolicyDecision.deny(f"reviewer {reviewer!r} is not an enabled agent")
        return PolicyDecision.ok()

    def check_attempt_budget(self, attempt_count: int) -> PolicyDecision:
        if attempt_count >= self.config.max_attempts_per_task:
            return PolicyDecision.deny(
                f"attempt budget exhausted ({attempt_count}/{self.config.max_attempts_per_task})"
            )
        return PolicyDecision.ok()

    def check_review_budget(self, review_cycles: int) -> PolicyDecision:
        if review_cycles > self.config.max_review_cycles:
            return PolicyDecision.deny(
                f"review/fix cycle budget exhausted "
                f"({review_cycles}/{self.config.max_review_cycles})"
            )
        return PolicyDecision.ok()

    # ------------------------------------------------------------ diffs

    def check_diff_paths(self, changed_paths: list[str]) -> PolicyDecision:
        """Reject diffs touching protected paths, .git internals, or escapes."""
        violations: list[str] = []
        for raw in changed_paths:
            path = PurePosixPath(raw)
            if path.is_absolute():
                violations.append(f"absolute path in diff: {raw}")
                continue
            if ".." in path.parts:
                violations.append(f"path traversal in diff: {raw}")
                continue
            parts = path.parts
            if parts and parts[0] == ".git":
                violations.append(f"diff touches .git internals: {raw}")
                continue
            if any(p == "hooks" and i > 0 and parts[i - 1] == ".git" for i, p in enumerate(parts)):
                violations.append(f"diff touches git hooks: {raw}")
                continue
            for protected in self.config.protected_paths:
                protected_parts = PurePosixPath(protected).parts
                if parts[: len(protected_parts)] == protected_parts:
                    violations.append(f"diff touches protected path {protected!r}: {raw}")
                    break
        if violations:
            return PolicyDecision.deny(*violations)
        return PolicyDecision.ok()

    # ------------------------------------------------------------- push

    def check_push(self) -> PolicyDecision:
        if not self.config.allow_push:
            return PolicyDecision.deny(
                "pushing is disabled by policy (set policy.allow_push = true to opt in)"
            )
        return PolicyDecision.ok()
