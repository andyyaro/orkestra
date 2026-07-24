"""Unit tests: fake worker directives (run in-process for coverage)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from orkestra.adapters import fake_worker


def run_worker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    instructions: str,
    *,
    kind: str = "implement",
    cwd: Path,
    argv: list[str] | None = None,
    json_schema: dict[str, Any] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    brief = {
        "task_id": "t1",
        "run_id": "r1",
        "title": "unit",
        "kind": kind,
        "instructions": instructions,
        "cwd": str(cwd),
        "timeout_s": 30,
        "json_schema": json_schema,
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(brief)))
    code = fake_worker.main(argv or [])
    out = capsys.readouterr().out
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "garbage", "raw": line})
    return code, events


def final(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if e.get("type") == "result")


class TestDirectives:
    def test_detect_handshake(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert fake_worker.main(["--orkestra-detect"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["protocol"] == "orkestra-jsonl/1"

    def test_default_implement_writes_marker(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        code, events = run_worker(monkeypatch, capsys, "do the thing", cwd=tmp_path)
        assert code == 0
        assert final(events)["status"] == "ok"
        assert (tmp_path / "fake-t1.txt").exists()

    def test_write_and_text(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:write:sub/x.txt:hello\nFAKE:text:custom",
            cwd=tmp_path,
        )
        assert (tmp_path / "sub" / "x.txt").read_text() == "hello\n"
        assert final(events)["final_text"] == "custom"

    def test_write_outside_workspace_refused(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(monkeypatch, capsys, "FAKE:write:../escape.txt:oops", cwd=tmp_path)
        assert final(events)["status"] == "error"
        assert final(events)["error_kind"] == "policy"
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_fail(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(monkeypatch, capsys, "FAKE:fail:boom", cwd=tmp_path)
        assert final(events)["status"] == "error"
        assert final(events)["error_detail"] == "boom"

    def test_fail_if_agent_scoping(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        argv = ["--agent-name", "alpha"]
        _, events = run_worker(
            monkeypatch, capsys, "FAKE:fail_if_agent:alpha", cwd=tmp_path, argv=argv
        )
        assert final(events)["status"] == "error"
        # Other agent unaffected.
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:fail_if_agent:alpha",
            cwd=tmp_path,
            argv=["--agent-name", "beta"],
        )
        assert final(events)["status"] == "ok"
        # Review role unaffected even for the named agent.
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:fail_if_agent:alpha",
            cwd=tmp_path,
            argv=argv,
            kind="review",
            json_schema={"type": "object"},
        )
        assert final(events)["status"] == "ok"

    def test_review_defaults_to_approval(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(
            monkeypatch,
            capsys,
            "please review",
            kind="review",
            cwd=tmp_path,
            json_schema={"type": "object"},
        )
        assert final(events)["structured"]["approve"] is True

    def test_reject(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:reject:bad code",
            kind="review",
            cwd=tmp_path,
            json_schema={"type": "object"},
        )
        verdict = final(events)["structured"]
        assert verdict["approve"] is False
        assert verdict["findings"] == ["bad code"]

    def test_reject_once_stateful(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:reject_once",
            kind="review",
            cwd=tmp_path,
            json_schema={"type": "object"},
        )
        assert final(events)["structured"]["approve"] is False
        _, events = run_worker(
            monkeypatch,
            capsys,
            "FAKE:reject_once",
            kind="review",
            cwd=tmp_path,
            json_schema={"type": "object"},
        )
        assert final(events)["structured"]["approve"] is True

    def test_reject_once_ignored_for_implementer(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(monkeypatch, capsys, "FAKE:reject_once", cwd=tmp_path)
        assert final(events)["status"] == "ok"
        assert not (tmp_path / ".fake-reject-done").exists()

    def test_structured_passthrough(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(
            monkeypatch,
            capsys,
            'FAKE:structured:{"answer": 42}',
            cwd=tmp_path,
            json_schema={"type": "object"},
        )
        assert final(events)["structured"] == {"answer": 42}

    def test_exit_code(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        code, _ = run_worker(monkeypatch, capsys, "FAKE:exit:3", cwd=tmp_path)
        assert code == 3

    def test_silent_no_result(self, monkeypatch, capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
        _, events = run_worker(monkeypatch, capsys, "FAKE:silent", cwd=tmp_path)
        assert not any(e.get("type") == "result" for e in events)

    def test_invalid_brief_json(self, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        code = fake_worker.main([])
        out = capsys.readouterr().out
        assert code == 1
        assert "invalid brief" in out
