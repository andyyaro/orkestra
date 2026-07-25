# Installation

## Requirements

- Python ≥ 3.12
- Git ≥ 2.20 (worktree support)
- macOS or Linux (Windows is untested; see ../ROADMAP.md)
- At least **two** agent CLIs installed and signed in with their own
  official flows, for example:
  - Claude Code: `claude` — https://code.claude.com/docs
  - OpenAI Codex CLI: `codex` — sign in with `codex login`
  - Google Antigravity CLI: `agy` — `curl -fsSL https://antigravity.google/cli/install.sh | bash`
  - Gemini CLI: `gemini` (API-key/Vertex auth) — `npm i -g @google/gemini-cli`

Orkestra never reads or copies agent credentials; each CLI manages its
own login.

## Install Orkestra

With [uv](https://docs.astral.sh/uv/) (recommended — isolated tool
install):

```bash
uv tool install orkestra-runtime
# with the optional live TUI (orkestra watch):
uv tool install 'orkestra-runtime[tui]'
```

With pip:

```bash
pip install orkestra-runtime
```

From a clone (development):

```bash
git clone https://github.com/andyyaro/orkestra
cd orkestra
uv sync
uv run orkestra --version
```

## Verify

```bash
orkestra --version
mkdir demo && cd demo
orkestra init .
orkestra doctor        # every check should be green for ≥2 agents
```

## Uninstall / cleanup

```bash
uv tool uninstall orkestra-runtime     # or: pip uninstall orkestra-runtime
```

Per-project state lives only in `.orkestra/` inside each project
(gitignored). Remove it to reset a project:

```bash
rm -rf .orkestra
git branch --list 'ork/*'              # inspect leftover run branches
git branch -D <branch>                 # delete the ones you don't want
```

Orkestra keeps no persistent state outside your project directories (the
codex adapter writes short-lived schema files, and `orkestra demo` a
scratch repository, into the system temp directory).
