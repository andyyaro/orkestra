"""Contract test kit for adapters.

Third-party adapter authors run this against their adapter to verify
protocol compliance without touching Orkestra internals:

    from orkestra.adapters.testkit import run_contract_suite
    report = await run_contract_suite(my_adapter, tmp_dir)
    assert report.passed, report.summary()

The suite only exercises the adapter's own process; it never invokes a
real LLM CLI (scenarios are driven through the adapter's command).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from orkestra.adapters.base import AgentAdapter
from orkestra.adapters.runner import run_invocation
from orkestra.schemas.agent import AgentEvent, ErrorKind, ResultStatus
from orkestra.schemas.common import TaskKind
from orkestra.schemas.task import TaskBrief


@dataclass
class ContractCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ContractReport:
    checks: list[ContractCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        return "\n".join(
            f"{'PASS' if c.passed else 'FAIL'} {c.name}" + (f" — {c.detail}" if c.detail else "")
            for c in self.checks
        )


def _brief(cwd: Path, instructions: str, kind: TaskKind = TaskKind.IMPLEMENT,
           timeout_s: int = 30, json_schema: dict[str, object] | None = None) -> TaskBrief:
    return TaskBrief(
        task_id="contract", run_id="contract", title="contract check",
        kind=kind, instructions=instructions, cwd=str(cwd), timeout_s=timeout_s,
        json_schema=json_schema,
    )


async def run_contract_suite(adapter: AgentAdapter, work_dir: Path) -> ContractReport:
    """Run the golden scenarios against a (scriptable) adapter."""
    report = ContractReport()
    events: list[AgentEvent] = []

    def collect(event: AgentEvent) -> None:
        events.append(event)

    async def invoke(instructions: str, **kwargs: object) -> object:
        brief = _brief(work_dir, instructions, **kwargs)  # type: ignore[arg-type]
        return await run_invocation(
            adapter.build_invocation(brief), adapter.make_parser(brief), collect
        )

    # 1. Detection handshake
    info = await adapter.detect()
    report.checks.append(
        ContractCheck("detect", info.available, info.detail)
    )
    if not info.available:
        return report

    # 2. Happy path
    result = await invoke("FAKE:text:hello contract")
    ok = (
        getattr(result, "status", None) is ResultStatus.OK
        and "hello contract" in getattr(result, "final_text", "")
    )
    report.checks.append(ContractCheck("happy_path", ok, str(result)[:200] if not ok else ""))

    # 3. Scripted failure surfaces as an error result (not an exception)
    result = await invoke("FAKE:fail:contract-failure")
    ok = getattr(result, "status", None) is ResultStatus.ERROR
    report.checks.append(ContractCheck("error_result", ok))

    # 4. Non-zero exit is normalized to a crash-like error
    result = await invoke("FAKE:exit:3")
    ok = (
        getattr(result, "status", None) is ResultStatus.ERROR
        and getattr(result, "error_kind", None)
        in (ErrorKind.CRASH, ErrorKind.INVALID_OUTPUT)
    )
    report.checks.append(ContractCheck("nonzero_exit", ok))

    # 5. Garbage output does not break the parser
    result = await invoke("FAKE:garbage\nFAKE:text:after garbage")
    ok = getattr(result, "status", None) is ResultStatus.OK
    report.checks.append(ContractCheck("garbage_tolerated", ok))

    # 6. Missing result event -> invalid_output
    result = await invoke("FAKE:silent")
    ok = getattr(result, "error_kind", None) is ErrorKind.INVALID_OUTPUT
    report.checks.append(ContractCheck("missing_result", ok))

    # 7. Timeout enforced by the runner
    result = await invoke("FAKE:sleep:15", timeout_s=2)
    ok = getattr(result, "error_kind", None) is ErrorKind.TIMEOUT
    report.checks.append(ContractCheck("timeout", ok))

    # 8. Cancellation
    brief = _brief(work_dir, "FAKE:sleep:15", timeout_s=30)
    cancel = asyncio.Event()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.5)
        cancel.set()

    canceller = asyncio.ensure_future(cancel_soon())
    result2 = await run_invocation(
        adapter.build_invocation(brief), adapter.make_parser(brief), collect, cancel
    )
    await canceller
    ok = result2.error_kind is ErrorKind.CANCELLED
    report.checks.append(ContractCheck("cancellation", ok))

    # 9. Structured output when a schema is requested
    result = await invoke(
        'FAKE:structured:{"answer": 42}',
        json_schema={"type": "object"},
    )
    ok = (
        getattr(result, "status", None) is ResultStatus.OK
        and getattr(result, "structured", None) == {"answer": 42}
    )
    report.checks.append(ContractCheck("structured_output", ok))

    return report
