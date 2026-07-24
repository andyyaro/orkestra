# Environment Changes

Append-only record of machine-level modifications made during the Orkestra
build. Project-local changes (inside this repository) are tracked by Git and
are not listed here.

| Date | Change | Command | Reversal |
|---|---|---|---|
| 2026-07-24 | Installed Gemini CLI 0.52.0 globally | `npm install -g @google/gemini-cli` | `npm uninstall -g @google/gemini-cli` |
| 2026-07-24 | Attempted to start Docker Desktop (app launch only, no configuration change) | `open -a Docker` | Quit Docker Desktop |
| 2026-07-24 | Antigravity CLI (`agy` 1.1.6) installed and authenticated **by the user** (not by the build session); recorded here for completeness | user-performed | user-managed |
