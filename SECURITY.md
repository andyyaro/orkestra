# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.5.x | ✅ |
| 0.4.x | ⚠️ previous minor |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use GitHub's private vulnerability reporting on
https://github.com/andyyaro/orkestra/security/advisories/new.

Include: affected version, reproduction steps, impact assessment, and any
suggested fix. You will receive an acknowledgment within 7 days. Please
allow up to 90 days for a coordinated fix before public disclosure.

## Scope notes

- Orkestra spawns coding-agent CLIs that can edit files and run commands
  inside isolated Git worktrees. Reports about agent behavior *inside its
  sandboxed workspace under a user-chosen autonomy mode* are usually not
  Orkestra vulnerabilities; escapes from the workspace scope, policy
  bypasses, injection through Orkestra's own command construction, state
  corruption, or secret exposure in logs/reports absolutely are.
- The threat model lives at `docs/security/THREAT_MODEL.md`.
