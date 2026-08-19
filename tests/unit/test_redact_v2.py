"""Table-driven redaction regression tests (dogfood finding 5).

Every "verified miss" from docs/development/SELF_REVIEW.md appears here
as a positive case; the benign false-positive examples appear as
negative cases. All fixtures are deliberately fake and scanner-safe.
"""

from __future__ import annotations

import json

import pytest

from orkestra.redact import REDACTED, redact, redact_structure

# (case id, input text, substring that must be gone)
POSITIVE = [
    # --- verified misses from the dogfood review, now covered ---
    ("aws-session-token", "AWS_SESSION_TOKEN=FAKEQoDYXdzEXAMPLEtoken", "FAKEQoDYXdz"),
    ("gcp-private-key-data", '{"privateKeyData":"RkFLRUZBS0VGQUtF"}', "RkFLRUZBS0VGQUtF"),
    ("azure-account-key", "AccountKey=RkFLRUtFWUZBS0VLRVk=", "RkFLRUtFWUZBS0VLRVk"),
    ("azure-sas-sig", "https://x.blob.example/?sv=2024&sig=FAKESIGFAKESIG123", "FAKESIGFAKESIG123"),
    ("gitlab-env-token", "GITLAB_TOKEN=glpat-FAKEFAKEFAKEFAKE", "glpat-FAKEFAKEFAKEFAKE"),
    ("gitlab-bare-pat", "header glpat-FAKE1234567890ab trailer", "glpat-FAKE1234567890ab"),
    ("slack-app-token", "SLACK_APP_TOKEN=xapp-1-FAKEFAKE-1234567890", "xapp-1-FAKEFAKE"),
    ("npm-npmrc", "//registry.npmjs.org/:_authToken=FAKE_NPM_TOKEN_123", "FAKE_NPM_TOKEN_123"),
    ("npm-modern", "npm_FAKEFAKEFAKEFAKEFAKE12345", "npm_FAKEFAKEFAKEFAKEFAKE12345"),
    ("pypi-token", "pypi-FAKEFAKEFAKEFAKE", "pypi-FAKEFAKEFAKEFAKE"),
    ("db-url-password", "DATABASE_URL=postgresql://alice:FAKEPW123@db.invalid/app", "FAKEPW123"),
    ("json-bearer-header", '{"Authorization":"Bearer FAKE.opaque.value"}', "FAKE.opaque"),
    ("plain-token-assignment", "token=FAKETOKENVALUE123", "FAKETOKENVALUE123"),
    ("json-quoted-password", '{"password":"FAKEPASS99"}', "FAKEPASS99"),
    ("camelcase-apikey", 'apiKey: "FAKEKEY9876"', "FAKEKEY9876"),
    # --- previously covered families must stay covered ---
    ("anthropic-key", "sk-ant-api03-FAKEFAKEFAKEFAKE", "FAKEFAKEFAKEFAKE"),
    ("openai-key", "sk-proj-FAKEFAKEFAKEFAKEFAKE", "sk-proj-FAKE"),
    ("github-classic", "ghp_FAKEFAKEFAKEFAKEFAKEfake12345", "ghp_FAKE"),
    ("github-fine-grained", "github_pat_FAKE1234567890_FAKEfake", "github_pat_FAKE"),
    ("google-api-key", "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKE-NO", "AIzaFAKE"),
    ("aws-akid", "AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7"),
    ("slack-bot", "xoxb-NOTAREALTOKEN-abcdefghijklmnop", "xoxb-NOTAREALTOKEN"),
    ("jwt", "eyJFAKEHEADERFAKE.eyJFAKEBODYFAKE.FAKESIG", "eyJFAKEHEADER"),
    ("bearer-raw", "Authorization: Bearer FAKE_OPAQUE_123", "FAKE_OPAQUE_123"),
    (
        "pem-block",
        "-----BEGIN RSA PRIVATE KEY-----\nRkFLRQ==\n-----END RSA PRIVATE KEY-----",
        "RkFLRQ",
    ),
    ("aws-secret-assignment", "aws_secret_access_key = FAKEsecretFAKEsecret", "FAKEsecret"),
    ("generic-secret", 'client_secret="FAKECLIENTSECRET"', "FAKECLIENTSECRET"),
]

# (case id, input text) - must pass through UNCHANGED
NEGATIVE = [
    ("status-missing", "auth_token=missing"),
    ("template-var", 'password="${DB_PASSWORD}"'),
    ("subshell-template", "secret=$(vault read app)"),
    ("status-configured", "api-key: configured"),
    ("path-value", "private_key=/etc/app/public.pem"),
    ("status-disabled-with-trailer", "password=disabled,retry_count=3"),
    ("status-none", "token=none"),
    ("masked-already", "password=********"),
    ("short-value", "token=abc12"),
    ("plain-prose", "ordinary log line: tests passed in 3.2s"),
    ("url-no-password", "https://example.com/path?x=1"),
    ("word-containing-key", "the monkey=business of tokens"),
]


class TestPositiveRedaction:
    @pytest.mark.parametrize(("case", "text", "secret"), POSITIVE, ids=[c[0] for c in POSITIVE])
    def test_secret_removed(self, case: str, text: str, secret: str) -> None:
        out = redact(text)
        assert secret not in out, f"{case}: {out!r}"
        assert REDACTED in out


class TestNegativeRedaction:
    @pytest.mark.parametrize(("case", "text"), NEGATIVE, ids=[c[0] for c in NEGATIVE])
    def test_benign_untouched(self, case: str, text: str) -> None:
        assert redact(text) == text


class TestTargetedReplacement:
    def test_url_keeps_user_and_host(self) -> None:
        out = redact("postgresql://alice:FAKEPW@db.invalid/app")
        assert out == f"postgresql://alice:{REDACTED}@db.invalid/app"

    def test_no_over_consumption_past_comma(self) -> None:
        out = redact("password=FAKEPASS99,retry_count=3")
        assert "retry_count=3" in out


class TestStructuredRedaction:
    def test_sensitive_keys_replaced_recursively(self) -> None:
        data = {
            "Authorization": "Bearer FAKE",
            "nested": {"api_key": "FAKEKEY", "note": "hello"},
            "items": [{"session_token": "FAKETOK"}, "plain"],
            "count": 3,
        }
        out = redact_structure(data)
        assert out["Authorization"] == REDACTED
        assert out["nested"]["api_key"] == REDACTED
        assert out["nested"]["note"] == "hello"
        assert out["items"][0]["session_token"] == REDACTED
        assert out["count"] == 3

    def test_string_leaves_pass_through_text_redaction(self) -> None:
        out = redact_structure({"log": "found ghp_FAKEFAKEFAKEFAKEFAKEfake12345"})
        assert "ghp_FAKE" not in out["log"]

    def test_serialized_output_is_clean(self) -> None:
        data = {"headers": {"Authorization": "Bearer FAKEFAKE"}}
        assert "FAKEFAKE" not in json.dumps(redact_structure(data))

    def test_depth_bomb_defused(self) -> None:
        deep: dict = {"a": {}}
        node = deep["a"]
        for _ in range(40):
            node["a"] = {}
            node = node["a"]
        node["password"] = "FAKEDEEP"
        assert "FAKEDEEP" not in json.dumps(redact_structure(deep))
