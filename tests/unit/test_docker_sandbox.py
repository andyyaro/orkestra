"""Unit tests: docker sandbox argv construction and config validation."""

from __future__ import annotations

from orkestra.adapters.base import InvocationSpec
from orkestra.adapters.docker import (
    CONTAINER_WORKDIR,
    validate_sandbox_config,
    wrap_in_docker,
)
from orkestra.schemas.config import ProjectConfig


def make_spec() -> InvocationSpec:
    return InvocationSpec(
        argv=["python3", "agent.py"],
        cwd="/tmp/work tree",  # space on purpose: argv arrays must survive it
        env_extra={"AGENT_MODE": "x"},
        stdin_data=b'{"cwd": "/tmp/work tree", "task_id": "t"}',
        timeout_s=120,
    )


class TestWrapInDocker:
    def test_hardening_flags_present(self) -> None:
        spec = wrap_in_docker(make_spec(), "python:3.12-slim", uid=501, gid=20)
        argv = spec.argv
        assert argv[:4] == ["docker", "run", "--rm", "-i"]
        for flag in (
            ["--network", "none"],
            ["--cap-drop", "ALL"],
            ["--security-opt", "no-new-privileges"],
            ["--read-only"],
            ["--pids-limit", "256"],
            ["--user", "501:20"],
            ["-v", f"/tmp/work tree:{CONTAINER_WORKDIR}"],
            ["-w", CONTAINER_WORKDIR],
        ):
            joined = " ".join(argv)
            assert " ".join(flag) in joined, flag
        # no docker socket, no privileged
        assert "docker.sock" not in " ".join(argv)
        assert "--privileged" not in argv

    def test_original_command_last(self) -> None:
        spec = wrap_in_docker(make_spec(), "img:1")
        assert spec.argv[-2:] == ["python3", "agent.py"]
        assert spec.argv[-3] == "img:1"

    def test_env_extra_forwarded_into_container(self) -> None:
        spec = wrap_in_docker(make_spec(), "img:1")
        assert "AGENT_MODE=x" in spec.argv
        assert spec.env_extra == {}

    def test_stdin_brief_paths_rewritten(self) -> None:
        spec = wrap_in_docker(make_spec(), "img:1")
        assert spec.stdin_data is not None
        assert b"/tmp/work tree" not in spec.stdin_data
        assert CONTAINER_WORKDIR.encode() in spec.stdin_data

    def test_timeout_preserved(self) -> None:
        assert wrap_in_docker(make_spec(), "img:1").timeout_s == 120


class TestValidateSandboxConfig:
    def make_config(self, agents: dict) -> ProjectConfig:  # type: ignore[type-arg]
        return ProjectConfig.model_validate(
            {
                "version": 1,
                "project": {"name": "d"},
                "agents": agents,
                "director": {"agent": next(iter(agents))},
                "policy": {"sandbox": "docker"},
            }
        )

    def test_vendor_cli_rejected(self) -> None:
        config = self.make_config(
            {
                "claude": {"adapter": "claude-code"},
                "b": {"adapter": "fake", "sandbox_image": "img:1"},
            }
        )
        errors = validate_sandbox_config(config)
        assert any("vendor CLIs cannot run" in e for e in errors)

    def test_missing_image_rejected(self) -> None:
        config = self.make_config(
            {
                "a": {"adapter": "fake", "sandbox_image": "img:1"},
                "b": {"adapter": "fake"},
            }
        )
        errors = validate_sandbox_config(config)
        assert len(errors) == 1 and "sandbox_image" in errors[0]

    def test_valid_config_passes(self) -> None:
        config = self.make_config(
            {
                "a": {"adapter": "fake", "sandbox_image": "img:1"},
                "b": {"adapter": "external", "command": ["/x"], "sandbox_image": "img:2"},
            }
        )
        assert validate_sandbox_config(config) == []
