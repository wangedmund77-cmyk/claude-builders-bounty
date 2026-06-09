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
- high-risk system operations: `mkfs`, raw `dd ... of=/dev/...` writes, and
  recursive `chmod 777 /`
- Bash fork bombs that define and immediately call a recursively piped
  background function, including the classic `:(){ :|:& };:` shape
- remote installer scripts piped directly into a shell, such as
  `curl https://example.invalid/install.sh | bash` or `wget -qO- ... | sh`

The same checks are applied to commands wrapped by shell execution helpers such
as `bash -c 'rm -rf build'` or `sh -lc 'git push --force'`.

When a command is blocked, the hook exits successfully and prints the current
Claude Code `PreToolUse` decision schema on stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked destructive Bash command: ..."
  }
}
```

Blocked attempts are appended to `~/.claude/hooks/blocked.log` as JSON lines with:

- timestamp
- attempted command
- project path
- reason

The hook creates `~/.claude/hooks` with user-only permissions, writes
`blocked.log` as user-read/write only, and refuses to write the audit log through
a symlinked log path.

## Manual Check

```bash
python3 hooks/destructive-bash-guard/destructive_bash_guard.py < hooks/destructive-bash-guard/samples/safe-input.json
python3 hooks/destructive-bash-guard/destructive_bash_guard.py < hooks/destructive-bash-guard/samples/dangerous-input.json
```

Expected result: the safe sample exits `0` without writing a block log entry; the dangerous sample exits `0`, prints a structured deny decision on stdout, and appends a new JSON line to `~/.claude/hooks/blocked.log`.
