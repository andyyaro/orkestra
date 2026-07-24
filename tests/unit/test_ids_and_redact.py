"""Unit tests: id generation, slug validation, secret redaction."""

from __future__ import annotations

import pytest

from orkestra.ids import (
    branch_name,
    integration_branch,
    is_valid_slug,
    new_id,
    require_slug,
    worktree_dirname,
)
from orkestra.redact import REDACTED, redact, redact_mapping


class TestIds:
    def test_new_id_unique_and_prefixed(self) -> None:
        a, b = new_id("task"), new_id("task")
        assert a != b
        assert a.startswith("task_")

    @pytest.mark.parametrize("value", ["claude", "codex-cli", "a1", "x" * 64, "a.b_c-d"])
    def test_valid_slugs(self, value: str) -> None:
        assert is_valid_slug(value)

    @pytest.mark.parametrize(
        "value",
        ["", "UPPER", "has space", "-leading", "x" * 65, "sneaky/../path", "a;rm -rf"],
    )
    def test_invalid_slugs(self, value: str) -> None:
        assert not is_valid_slug(value)
        with pytest.raises(ValueError, match="not a valid identifier"):
            require_slug(value, "agent")

    def test_branch_names_are_generated_not_injected(self) -> None:
        assert branch_name("run_ab12", "task_cd34") == "ork/run_ab12/task_cd34"
        assert integration_branch("run_ab12") == "ork/run_ab12/integration"
        with pytest.raises(ValueError, match="reference validation"):
            branch_name("run_ab12", "task; rm -rf /")

    def test_worktree_dirname_unique(self) -> None:
        assert worktree_dirname("r", "t") != worktree_dirname("r", "t")


class TestRedact:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-api03-abcdefghijklmnop",
            "sk-proj-ABCDEFGHIJKLMNOPqrstuv123456",
            "ghp_abcdefghijklmnopqrstuvwxyz012345",
            "github_pat_11ABCDEFG0123456789_abcdef",
            "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKE-NO",
            "AKIAIOSFODNN7EXAMPLE",
            "xoxb-NOTAREALTOKEN-abcdefghijklmnop",
        ],
    )
    def test_token_shapes_redacted(self, secret: str) -> None:
        assert secret not in redact(f"before {secret} after")

    def test_assignment_patterns_redacted(self) -> None:
        text = 'api_key = "supersecretvalue123"\npassword: hunter22222'
        out = redact(text)
        assert "supersecretvalue123" not in out
        assert "hunter22222" not in out

    def test_pem_block_redacted(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
        assert "MIIabc" not in redact(pem)

    def test_bearer_header_redacted(self) -> None:
        assert "abc.def" not in redact("Authorization: Bearer abc.def")

    def test_plain_text_untouched(self) -> None:
        text = "ordinary log line: tests passed in 3.2s"
        assert redact(text) == text

    def test_mapping_redaction_by_key(self) -> None:
        out = redact_mapping({"GITHUB_TOKEN": "x", "PATH": "/usr/bin"})
        assert out["GITHUB_TOKEN"] == REDACTED
        assert out["PATH"] == "/usr/bin"
