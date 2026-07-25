# ADR-0009: Docker sandbox — external agents only in v0.2

Date: 2026-07-24 · Status: accepted

## Context

`policy.sandbox = "docker"` was reserved in v0.1 and refused with an
explanation. The demand is real: external-command agents (the
`orkestra-jsonl/1` protocol) run arbitrary user-declared binaries with
no vendor-provided sandbox of their own, unlike Codex (Seatbelt/
Landlock), Antigravity, and Gemini (sandbox modes), or Claude Code
(permission policy).

The blocking constraint from v0.1 still holds for **vendor CLIs**:
they authenticate through host credential stores (keychain,
`~/.codex/auth.json`, `~/.gemini`). Containerizing them requires either
mounting those stores into the container — which violates Orkestra's
"never touch credential stores" rule and would hand tokens to the
sandboxed process — or vendor-supported containerized auth flows that
do not exist today for subscription login.

## Decision

1. Implement Docker sandboxing **only for `external` and `fake`
   adapters** in v0.2. When `policy.sandbox = "docker"`:
   - agents with `external`/`fake` adapters run inside a container the
     user names per agent (`agents.<name>.sandbox_image`);
   - configuring a vendor-CLI adapter (claude-code, codex-cli,
     antigravity-cli, gemini-cli) alongside `sandbox = "docker"` remains
     a configuration error with the credential-exposure explanation.
2. Hardened invocation, built as an argv transformation of the normal
   `InvocationSpec` (`orkestra.adapters.docker.wrap_in_docker`):

   ```text
   docker run --rm -i
     --network none
     --cap-drop ALL
     --security-opt no-new-privileges
     --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m
     --memory 2g --cpus 2 --pids-limit 256
     --user <host-uid>:<host-gid>
     -v <worktree>:/work -w /work
     -e HOME=/tmp
     <sandbox_image> <original argv>
   ```

   - Only the task worktree is mounted (read-write); nothing else.
   - No network by default: the agent works offline against /work.
   - Non-root with the host uid/gid so worktree writes stay owned by
     the user; no Docker socket; no added capabilities.
3. The brief's `cwd` inside the container is `/work`; Orkestra rewrites
   the brief path accordingly, and the stdin JSON brief carries the
   container path so protocol agents behave identically.
4. `orkestra doctor` reports Docker daemon readiness as a hard check
   when any enabled agent will run sandboxed.

## Rationale

- The transformation happens at the runner boundary, so process
  supervision, timeouts, process-group kill (docker run is the group
  leader; SIGKILL tears down the container via `--rm`+`--init`-less
  semantics), streaming, and normalization are unchanged.
- Refusing vendor CLIs keeps the credential rule intact and the failure
  mode honest, rather than shipping a sandbox that silently mounts
  tokens.

## Consequences

- Vendor-CLI containerization stays on the roadmap, contingent on
  vendor-supported container auth (e.g. short-lived tokens like
  `claude setup-token` injected per invocation — explicitly user-opt-in
  and never read from stores by Orkestra).
- Container teardown on timeout relies on killing `docker run` and
  `--rm`; a follow-up could use `--cidfile` + `docker kill` for
  belt-and-braces cleanup of daemon-side strays.
