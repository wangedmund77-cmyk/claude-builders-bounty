# Destructive Bash Guard Hook

Claude Code `PreToolUse` hook for blocking destructive Bash commands before they run.

## Install

From this repository:

```bash
python3 hooks/destructive-bash-guard/destructive_bash_guard.py --install
```

That command copies the hook to `~/.claude/hooks/destructive-bash-guard.py`, makes it executable, and adds a Bash `PreToolUse` entry to `~/.claude/settings.json`.

## What It Blocks

- `rm -rf` and equivalent recursive force variants such as `rm -fr`
- `git push --force`, `git push --force-with-lease`, and `git push -f`
- `DROP TABLE`
- `TRUNCATE`
- `DELETE FROM ...` without a `WHERE` clause

Blocked attempts are appended to `~/.claude/hooks/blocked.log` as JSON lines with:

- timestamp
- attempted command
- project path
- reason

## Manual Check

```bash
printf '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/demo"}}' | ~/.claude/hooks/destructive-bash-guard.py
```

Expected result: exit code `2`, a clear block message on stderr, and a new entry in `~/.claude/hooks/blocked.log`.
