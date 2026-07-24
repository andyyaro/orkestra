# Self-Review: Secret Redaction Module (Dogfood Evidence)

Provenance: produced 2026-07-24 by **Orkestra orchestrating its own
repository** (run `run_cb25ff11`): the Claude director planned two tasks
after plan challenges from Codex and Antigravity; the analysis below was
implemented by **codex** and independently reviewed/approved by
**claude**. A second task (formatting this into a polished document) was
rejected twice by the Codex reviewer under a deliberately tight
1-review-cycle budget and skipped by the operator at the human gate —
the bounded-loop and human-escalation behavior working as designed.
This file curates codex's approved analysis verbatim (worktree paths
sanitized). Findings feed the roadmap; see also
`docs/development/evidence/DOGFOOD_RUN_REPORT.md`.

---

> **Resolution (v0.1.1, 2026-07-24):** every verified miss and
> false-positive class below was addressed in `src/orkestra/redact.py`
> and locked in by `tests/unit/test_redact_v2.py`. Remaining by design:
> `redact()` still favors recall over precision for unrecognized
> assignment values.

Preflight: `docs/development/SELF_REVIEW.md` does not exist, so the analysis proceeded. The worktree and index remain unchanged; both diff checks returned exit code 0, and `git status --porcelain` was empty.

## 1. Credential-format coverage

Ratings apply to `redact(text)`, which sequentially substitutes `_PATTERNS` ([redact.py:14](src/orkestra/redact.py:14), [redact.py:50](src/orkestra/redact.py:50)). The separate `redact_mapping()` only helps when explicitly called on a mapping; it is not automatically applied by `redact()` ([redact.py:57](src/orkestra/redact.py:57)).

All credential-like examples below are deliberately malformed with placeholders, invalid structure, or wrong length.

| Category | Classification | Trace against actual patterns |
|---|---|---|
| AWS credentials | **PARTIALLY/CONTEXTUALLY COVERED** | `\b(?:AKIA\|ASIA)[0-9A-Z]{16}\b` catches common long-term and temporary access-key IDs. `aws_secret_access_key[=:]\S+` catches the secret only under that exact field name, case-insensitively. Bare secret access keys and the standard `AWS_SESSION_TOKEN=` name are missed; the latter cannot match `session_token` because the preceding underscore is a word character. Verified miss: `AWS_SESSION_TOKEN=FAKE_EXAMPLE_SHORT`. AWS documents all three standard names: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`. [AWS credential settings](https://docs.aws.amazon.com/sdkref/latest/guide/feature-static-credentials.html) |
| GCP credentials | **PARTIALLY/CONTEXTUALLY COVERED** | Google API keys beginning `AIza` with at least 30 following allowed characters match line 23. Service-account JSON containing a PEM `private_key` is caught by the PEM pattern, including JSON text with escaped newlines. However, JSON `"privateKeyData":"..."` containing the base64-encoded key response is missed: the generic alternative cannot match `privateKey` inside `privateKeyData`, and quoted JSON keys are unsupported. Verified miss: `{"privateKeyData":"EXAMPLE_FAKE_BASE64"}`. [Google service-account key formats](https://docs.cloud.google.com/iam/docs/keys-create-delete) |
| Azure credentials | **PARTIALLY/CONTEXTUALLY COVERED** | There is no Azure-specific pattern. An unquoted `api-key:` or `client_secret=` assignment is caught generically, but native Storage connection-string fields such as `AccountKey=` and `SharedAccessSignature=` are not alternatives. Bare Azure DevOps PATs are also missed. Verified miss: `AccountKey=EXAMPLE_FAKE_NOT_BASE64`. [Azure Storage connection-string formats](https://learn.microsoft.com/en-us/azure/storage/common/storage-configure-connection-string) |
| GitHub PATs | **COVERED** | Classic `ghp_...` matches `gh[pousr]_[A-Za-z0-9]{20,}` and fine-grained `github_pat_...` matches the following explicit pattern. These are GitHub’s documented PAT prefixes. [GitHub token formats](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github) |
| GitLab PATs | **PARTIALLY/CONTEXTUALLY COVERED** | No `glpat-` pattern exists. A PAT is caught inside a raw `Authorization: Bearer ...` header or under a recognized outer name such as `access_token=`, but bare tokens, `GITLAB_TOKEN=`, and GitLab’s `PRIVATE-TOKEN:` header are missed. Notably, plain `token=` is not in the generic alternatives. Verified miss: `GITLAB_TOKEN=glpat-EXAMPLE`. GitLab documents `glpat-` as the default PAT prefix. [GitLab token prefixes](https://docs.gitlab.com/security/tokens/) |
| Slack tokens | **PARTIALLY/CONTEXTUALLY COVERED** | `xox[baprs]-[A-Za-z0-9-]{10,}` covers the listed `xox*` families, including common `xoxb-` bot tokens. Slack app-level `xapp-` tokens are absent. Verified miss: `SLACK_APP_TOKEN=xapp-1-EXAMPLE-FAKE`. [Slack token types](https://docs.slack.dev/authentication/tokens/) |
| npm tokens | **PARTIALLY/CONTEXTUALLY COVERED** | Bare npm tokens have no matching format pattern. An unprefixed `authToken=...` happens to match the generic regex, but npm’s native registry-scoped `.npmrc` spelling `//host/:_authToken=...` does not: the underscore before `authToken` prevents the required leading word boundary. Verified miss: `//registry.npmjs.org/:_authToken=EXAMPLE_FAKE_SHORT`. [npm `.npmrc` authentication syntax](https://docs.npmjs.com/files/npmrc/) |
| PyPI tokens | **PARTIALLY/CONTEXTUALLY COVERED** | No explicit `pypi-` pattern exists. A normal `.pypirc` `password=...` assignment is caught generically, but a bare token is missed. Verified miss: `pypi-EXAMPLE`—deliberately much shorter than PyPI’s documented minimum payload. [PyPI token format](https://docs.pypi.org/api/secrets/) |
| JWTs | **COVERED** for ordinary compact signed JWT credentials | The line-30 pattern matches a bare three-segment Base64URL token beginning `eyJ`, subject to minimum segment lengths of 13, 10, and 5 characters respectively. Representative signed compact JWT construction matched regardless of surrounding assignment syntax. |
| Database/connection-string URLs | **PARTIALLY/CONTEXTUALLY COVERED** | There is no URL-userinfo pattern. A normal `DATABASE_URL=postgresql://user:password@host/db` is missed because `DATABASE_URL` is not a recognized key and no pattern examines `user:password@`. The whole URL is incidentally caught if assigned to `secret=` or another recognized generic name. Verified miss: `DATABASE_URL=postgresql://alice:EXAMPLE_FAKE@db.invalid/app`. |
| PEM private-key blocks | **COVERED** | The DOTALL pattern matches complete uppercase `BEGIN … PRIVATE KEY` / `END … PRIVATE KEY` blocks, including RSA, EC, OpenSSH, encrypted PKCS#8, and generic PKCS#8 labels ([redact.py:33](src/orkestra/redact.py:33)). It also matches such blocks embedded in JSON strings with literal `\\n` escapes. |
| Bearer tokens in headers | **PARTIALLY/CONTEXTUALLY COVERED** | Canonical raw `Authorization: Bearer opaque-token` and `Authorization=Bearer opaque-token` lines are covered case-insensitively by line 32. A JSON-serialized header map is missed because `"Authorization"` places a quote between the word and colon. This is relevant because persisted event data is passed through `json.dumps()` before `redact()` ([repo.py:341](src/orkestra/store/repo.py:341)). Verified miss: `{"Authorization":"Bearer <EXAMPLE_FAKE>"}`. A standard JWT bearer value would still be independently caught by the JWT pattern. |

## 2. Generic-pattern false positives

The exact verbose-mode pattern at [redact.py:40](src/orkestra/redact.py:40) is:

```regex
(?ix)
        \b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|
           client[_-]?secret|private[_-]?key|session[_-]?token)\b
        \s*[=:]\s*
        (?!\[REDACTED\])["']?[^\s"']{6,}["']?
```

False-positive risk is significant because the value test is only “at least six non-whitespace, non-quote characters.” It does not require entropy, a known credential prefix, or distinguish a secret from a status word, template, or path. Verified benign redactions include:

- Log line: `auth_token=missing`
- Config template: `password="${DB_PASSWORD}"`
- CLI status: `api-key: configured`
- Config path: `private_key=/etc/app/public.pem`
- Compact log metadata: `password=disabled,retry_count=3`

The last case also demonstrates over-redaction breadth: because comma and `=` are allowed by `[^\s"']`, the match can consume `,retry_count=3` along with the benign password status.

Conversely, the generic pattern is narrower than its comment suggests:

- Plain `token=...` is not an alternative and does not match.
- Quoted JSON keys such as `"password":"..."` do not match.
- Provider-prefixed names such as `GITLAB_TOKEN`, `AWS_SESSION_TOKEN`, and npm’s `_authToken` generally fail because of the word-boundary and allowed-name rules.
- Values shorter than six characters are never redacted, even when genuinely sensitive.

## 3. T3 comparison

**No strict mismatch found in T3’s enumerated pattern claims.**

T3 says:

> “a redaction filter is applied to all persisted logs and the support bundle, matching known secret shapes (`sk-...`, `ghp_...`, `github_pat_...`, AWS keys, bearer headers, PEM blocks, generic `key=value` credential patterns).”

This claim appears at [THREAT_MODEL.md:65](docs/security/THREAT_MODEL.md:65). Each named family has a corresponding implementation pattern:

- `sk-`: lines 16–18
- GitHub tokens: lines 20–21
- AWS access IDs and named secret assignments: lines 25–26
- Bearer headers: line 32
- PEM private keys: lines 34–36
- Credential assignments: lines 40–44

The coverage gaps above do not strictly contradict T3 because its list says “known secret shapes” and does not claim exhaustive detection of every provider format or serialization. The omission of plain `token=` does contradict the nearby code comment “token=...”, but that is an internal code-comment mismatch, not an explicit T3-text mismatch.

## 4. Prioritized improvements

1. Redact structured mappings before serialization. Recursively replace values under sensitive keys—including `authorization`, plain `token`, provider-prefixed variables, and camelCase variants—before `json.dumps()`. This closes JSON-header and quoted-key gaps broadly.

2. Add URL-aware credential handling for `scheme://user:password@host`, JDBC/ADO-style DSNs, and common connection-string fields while preserving non-secret URL portions.

3. Add cloud-native coverage for AWS session tokens and bare/contextual secret access keys, GCP encoded `privateKeyData`, Azure Storage `AccountKey`/SAS fields, and both Azure DevOps PAT formats.

4. Add explicit platform-token patterns for GitLab token families, Slack `xapp-`, current npm access tokens, and PyPI’s documented `pypi-` format.

5. Add table-driven positive and negative regression tests using scanner-safe fixtures. Include raw text, JSON, shell exports, native config files, headers, URLs, benign status words, templates, and paths; use these tests to narrow over-consumption by the generic value matcher.
