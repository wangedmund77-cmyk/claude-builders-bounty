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
- `git push --force`, `git push --force-with-lease`, `git push -f`,
  force refspecs such as `+main`, and `git -c push.force=true push`
- `git reset --hard`
- `DROP TABLE`
- `DROP DATABASE` and `DROP SCHEMA`
- `TRUNCATE`
- `DELETE FROM ...` without a `WHERE` clause
- high-risk system operations: `mkfs`, raw `dd ... of=/dev/...` writes, and
  recursive chmod permission-widening or lockout modes on critical paths such
  as `chmod -R 777 /` and `chmod -R 000 $HOME`
- recursive ownership rewrites on critical paths, such as
  `chown -R root:root /` and `chgrp --recursive staff $HOME`
- `find -delete` sweeps on critical paths, such as `find / -delete`
- filesystem signature wipes through `wipefs`, and shell redirects that write
  directly to raw block devices such as `/dev/sdb`
- irreversible file shredding through `shred`
- Bash fork bombs that define and immediately call a recursively piped
  background function, including the classic `:(){ :|:& };:` shape
- remote installer scripts piped directly into a shell, such as
  `curl https://example.invalid/install.sh | bash` or `wget -qO- ... | sh`

The same checks are applied to commands wrapped by shell execution helpers such
as `bash -c 'rm -rf build'` or `sh -lc 'git push --force'`, and through
`sudo`, `env`, or `command` wrappers such as `sudo -n rm -rf /tmp/build`.
Plain text inspection commands such as `grep 'DROP TABLE' docs.md` and
`sudo -u root echo rm -rf /tmp/build` are allowed when they are not piped or
redirected into another command.

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

Non-empty malformed hook payloads fail closed with the same structured deny
schema and are logged as `<invalid hook payload>`.

The hook creates `~/.claude/hooks` with user-only permissions, writes
`blocked.log` as user-read/write only, and refuses to write the audit log through
a symlinked log path.

## Manual Check

```bash
python3 hooks/destructive-bash-guard/destructive_bash_guard.py < hooks/destructive-bash-guard/samples/safe-input.json
python3 hooks/destructive-bash-guard/destructive_bash_guard.py < hooks/destructive-bash-guard/samples/dangerous-input.json
```

Expected result: the safe sample exits `0` without writing a block log entry; the dangerous sample exits `0`, prints a structured deny decision on stdout, and appends a new JSON line to `~/.claude/hooks/blocked.log`.
