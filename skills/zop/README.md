# zop — agent skill

An [agent skill](https://skills.sh) that teaches coding agents (Claude Code, Codex, Cursor, and 70+ more) how to drive the [`zop`](https://github.com/kingdomad/zop) Zotero CLI: which commands exist, how offline SQLite reads differ from Web API writes, and how to parse the JSON envelope output.

## Install

```bash
# from this repo, to Claude Code, non-interactive
npx skills add kingdomad/zop --skill zop -a claude-code -y

# or interactively pick agent and scope
npx skills add kingdomad/zop
```

This symlinks `SKILL.md` into the agent's skills directory (`.claude/skills/zop/` for Claude Code, project-scoped by default; add `-g` for global, `--copy` if symlinks aren't supported).

## What it gives the agent

- The full command map (collections / items / tags / notes / pdf / export / library stats).
- The output contract — `{ok, data, error, meta}` JSON envelope, exit codes (`0`/`1`/`2`), error codes (`not_found`, `auth_missing`, `conflict`, `api_error`).
- Guidance on the batch `plan` dry-run → execute workflow and per-item failure isolation.

The skill assumes `zop` is already installed (`uv tool install zop-cli`) and configured. It teaches *how to call* zop; it does not install it.

## Files

- `SKILL.md` — the skill itself (read by agents at runtime when triggered).
