"""Parser tests against golden output captured from the real CLIs.

Sample payloads mirror docs/research/samples/ (captured 2026-07-24).
"""

from __future__ import annotations

import json

from orkestra.adapters.antigravity_cli import AntigravityParser
from orkestra.adapters.claude_code import ClaudeParser
from orkestra.adapters.codex_cli import CodexParser
from orkestra.adapters.gemini_cli import GeminiParser
from orkestra.adapters.jsonl import extract_json_object, try_parse_json
from orkestra.schemas.agent import ErrorKind, ResultStatus


def feed(parser, lines: list[str], stderr: list[str] | None = None):  # type: ignore[no-untyped-def]
    events = []
    for line in lines:
        events.extend(parser.feed_line(line, is_stderr=False))
    for line in stderr or []:
        events.extend(parser.feed_line(line, is_stderr=True))
    return events


class TestClaudeParser:
    RESULT = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "OK",
            "session_id": "0c4a565f-6f9f-4d62-b2a2-871773cc365e",
            "num_turns": 1,
            "total_cost_usd": 0.0171116,
            "usage": {"input_tokens": 10, "output_tokens": 42, "cache_read_input_tokens": 17536},
        }
    )

    def test_happy_path(self) -> None:
        parser = ClaudeParser()
        feed(parser, [self.RESULT])
        result = parser.result(0, 3.6, "/work")
        assert result.status is ResultStatus.OK
        assert result.final_text == "OK"
        assert result.session is not None
        assert result.session.session_id.startswith("0c4a565f")
        assert result.usage.total_cost_usd == 0.0171116

    def test_api_retry_rate_limit_categorized(self) -> None:
        parser = ClaudeParser()
        retry = json.dumps(
            {"type": "system", "subtype": "api_retry", "error": "rate_limit", "attempt": 1}
        )
        error_result = json.dumps(
            {"type": "result", "is_error": True, "subtype": "error_during_execution", "result": ""}
        )
        feed(parser, [retry, error_result])
        result = parser.result(1, 1.0, "/work")
        assert result.status is ResultStatus.ERROR
        assert result.error_kind is ErrorKind.RATE_LIMIT

    def test_no_envelope_is_invalid_output(self) -> None:
        parser = ClaudeParser()
        feed(parser, ["random banner text"])
        result = parser.result(0, 1.0, "/work")
        assert result.error_kind is ErrorKind.INVALID_OUTPUT

    def test_structured_output_passthrough(self) -> None:
        parser = ClaudeParser()
        envelope = json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "{}",
                "session_id": "s",
                "structured_output": {"a": 1},
            }
        )
        feed(parser, [envelope])
        assert parser.result(0, 1.0, "/w").structured == {"a": 1}

    def test_assistant_text_streams(self) -> None:
        parser = ClaudeParser()
        message = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "thinking about it"},
                        {"type": "tool_use", "name": "Bash"},
                    ]
                },
            }
        )
        events = feed(parser, [message])
        kinds = [e.kind.value for e in events]
        assert kinds == ["text", "tool"]


class TestCodexParser:
    LINES = [
        json.dumps({"type": "thread.started", "thread_id": "019f957d-4f33-7e21-b4b6-38e78b78a0ee"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": "OK"},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 17144, "cached_input_tokens": 0, "output_tokens": 5},
            }
        ),
    ]

    def test_happy_path(self) -> None:
        parser = CodexParser(expect_structured=False)
        feed(parser, self.LINES)
        result = parser.result(0, 2.0, "/work")
        assert result.status is ResultStatus.OK
        assert result.final_text == "OK"
        assert result.session is not None
        assert result.session.session_id.startswith("019f957d")
        assert result.usage.input_tokens == 17144

    def test_error_event(self) -> None:
        parser = CodexParser(expect_structured=False)
        feed(parser, [json.dumps({"type": "error", "message": "stream disconnected"})])
        result = parser.result(1, 2.0, "/work")
        assert result.status is ResultStatus.ERROR

    def test_auth_error_from_stderr(self) -> None:
        parser = CodexParser(expect_structured=False)
        feed(parser, [], stderr=["Please run `codex login` to authenticate"])
        result = parser.result(1, 0.4, "/work")
        assert result.error_kind is ErrorKind.AUTH

    def test_structured_expected_but_missing(self) -> None:
        parser = CodexParser(expect_structured=True)
        feed(
            parser,
            [
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "no json"}}
                )
            ],
        )
        result = parser.result(0, 1.0, "/w")
        assert result.error_kind is ErrorKind.INVALID_OUTPUT

    def test_structured_ok(self) -> None:
        parser = CodexParser(expect_structured=True)
        feed(
            parser,
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": '{"verdict": true}'},
                    }
                )
            ],
        )
        assert parser.result(0, 1.0, "/w").structured == {"verdict": True}


class TestAntigravityParser:
    LINES = [
        json.dumps(
            {
                "event": "init",
                "conversation_id": "52861ad8",
                "init": {
                    "cwd": "/tmp",
                    "tools": ["run_command"],
                    "permission_mode": "request-review",
                },
            }
        ),
        json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "52861ad8",
                    "step_index": 2,
                    "state": "DONE",
                    "step_type": "agent_response",
                    "text_delta": "OK\n",
                    "usage": {"input_tokens": 9802, "output_tokens": 20},
                },
            }
        ),
        json.dumps(
            {
                "event": "result",
                "result": {
                    "conversation_id": "52861ad8",
                    "status": "SUCCESS",
                    "response": "OK\n",
                    "duration_seconds": 1.11,
                    "num_turns": 1,
                    "usage": {
                        "input_tokens": 9899,
                        "output_tokens": 24,
                        "thinking_tokens": 19,
                        "total_tokens": 9923,
                    },
                },
            }
        ),
    ]

    def test_happy_path(self) -> None:
        parser = AntigravityParser(expect_structured=False)
        feed(parser, self.LINES)
        result = parser.result(0, 1.2, "/work")
        assert result.status is ResultStatus.OK
        assert result.final_text.strip() == "OK"
        assert result.session is not None
        assert result.session.session_id == "52861ad8"
        assert result.usage.input_tokens == 9899

    def test_plain_text_fallback(self) -> None:
        # If --output-format disappears upstream, stdout is plain text.
        parser = AntigravityParser(expect_structured=False)
        feed(parser, ["Just a plain answer", "across two lines"])
        result = parser.result(0, 1.0, "/work")
        assert result.status is ResultStatus.OK
        assert "plain answer" in result.final_text

    def test_failure_status(self) -> None:
        parser = AntigravityParser(expect_structured=False)
        feed(
            parser,
            [
                json.dumps(
                    {
                        "event": "result",
                        "result": {"conversation_id": "x", "status": "FAILED", "response": ""},
                    }
                )
            ],
        )
        assert parser.result(0, 1.0, "/w").status is ResultStatus.ERROR

    def test_auth_error_heuristic(self) -> None:
        parser = AntigravityParser(expect_structured=False)
        feed(parser, [], stderr=["Please sign in to continue"])
        result = parser.result(1, 0.2, "/w")
        assert result.error_kind is ErrorKind.AUTH

    def test_structured_extraction_from_response(self) -> None:
        parser = AntigravityParser(expect_structured=True)
        feed(
            parser,
            [
                json.dumps(
                    {
                        "event": "result",
                        "result": {
                            "conversation_id": "x",
                            "status": "SUCCESS",
                            "response": 'Here you go:\n```json\n{"plan": []}\n```',
                        },
                    }
                )
            ],
        )
        assert parser.result(0, 1.0, "/w").structured == {"plan": []}


class TestGeminiParser:
    def test_auth_exit_41(self) -> None:
        parser = GeminiParser(expect_structured=False)
        stderr_json = json.dumps(
            {
                "session_id": "8180efc1",
                "error": {
                    "type": "Error",
                    "message": "Please set an Auth method in your settings.json",
                    "code": 41,
                },
            }
        )
        feed(parser, [], stderr=[stderr_json])
        result = parser.result(41, 0.5, "/work")
        assert result.error_kind is ErrorKind.AUTH
        assert "Auth method" in result.error_detail

    def test_json_envelope(self) -> None:
        parser = GeminiParser(expect_structured=False)
        feed(
            parser,
            [json.dumps({"response": "hello", "stats": {"tokens": {"input": 12, "output": 3}}})],
        )
        result = parser.result(0, 1.0, "/work")
        assert result.status is ResultStatus.OK
        assert result.final_text == "hello"
        assert result.usage.input_tokens == 12


class TestJsonHelpers:
    def test_try_parse_rejects_garbage(self) -> None:
        assert try_parse_json("not json") is None
        assert try_parse_json("[1,2]") is None  # arrays are not envelopes
        assert try_parse_json('{"a": 1}') == {"a": 1}

    def test_extract_from_fence(self) -> None:
        text = 'blah\n```json\n{"x": 1}\n```\nmore'
        assert extract_json_object(text) == {"x": 1}

    def test_extract_balanced_with_nested_braces_in_strings(self) -> None:
        text = 'prefix {"a": "with } brace", "b": {"c": 2}} suffix'
        assert extract_json_object(text) == {"a": "with } brace", "b": {"c": 2}}

    def test_extract_none(self) -> None:
        assert extract_json_object("no json here") is None


class TestCodexStrictSchema:
    def test_strict_transform(self) -> None:
        from orkestra.adapters.codex_cli import to_strict_schema
        from orkestra.schemas.director import ReviewVerdict

        schema = to_strict_schema(ReviewVerdict.model_json_schema())

        def check(node):  # type: ignore[no-untyped-def]
            if isinstance(node, dict):
                assert "default" not in node
                if node.get("type") == "object" and "properties" in node:
                    assert set(node["required"]) == set(node["properties"])
                    assert node["additionalProperties"] is False
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for item in node:
                    check(item)

        check(schema)


class TestEffortWiring:
    def test_antigravity_effort_flag(self) -> None:
        from orkestra.adapters.antigravity_cli import AntigravityCliAdapter
        from orkestra.schemas.common import TaskKind
        from orkestra.schemas.task import TaskBrief

        adapter = AntigravityCliAdapter(model="gemini-3.1-pro-high", effort="high")
        brief = TaskBrief(
            task_id="t",
            run_id="r",
            title="x",
            kind=TaskKind.IMPLEMENT,
            instructions="do",
            cwd="/tmp",
            timeout_s=60,
        )
        argv = adapter.build_invocation(brief).argv
        assert "--effort" in argv and argv[argv.index("--effort") + 1] == "high"
        assert "--model" in argv

    def test_codex_effort_config_override(self) -> None:
        from orkestra.adapters.codex_cli import CodexCliAdapter
        from orkestra.schemas.common import TaskKind
        from orkestra.schemas.task import TaskBrief

        adapter = CodexCliAdapter(effort="low")
        brief = TaskBrief(
            task_id="t",
            run_id="r",
            title="x",
            kind=TaskKind.IMPLEMENT,
            instructions="do",
            cwd="/tmp",
            timeout_s=60,
        )
        argv = adapter.build_invocation(brief).argv
        assert 'model_reasoning_effort="low"' in argv

    def test_no_effort_no_flags(self) -> None:
        from orkestra.adapters.antigravity_cli import AntigravityCliAdapter
        from orkestra.adapters.codex_cli import CodexCliAdapter
        from orkestra.schemas.common import TaskKind
        from orkestra.schemas.task import TaskBrief

        brief = TaskBrief(
            task_id="t",
            run_id="r",
            title="x",
            kind=TaskKind.IMPLEMENT,
            instructions="do",
            cwd="/tmp",
            timeout_s=60,
        )
        assert "--effort" not in AntigravityCliAdapter().build_invocation(brief).argv
        assert not any(
            "model_reasoning_effort" in a for a in CodexCliAdapter().build_invocation(brief).argv
        )
