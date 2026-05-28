#!/usr/bin/env python3
"""Claude Code PreToolUse hook that blocks destructive Bash commands."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import sys
from typing import Any


HOOK_NAME = "destructive-bash-guard.py"
BLOCK_LOG = "blocked.log"

DROP_TABLE_RE = re.compile(r"\bdrop\s+table\b", re.IGNORECASE)
TRUNCATE_RE = re.compile(r"\btruncate\b", re.IGNORECASE)
DELETE_FROM_RE = re.compile(r"\bdelete\s+from\b", re.IGNORECASE)
WHERE_RE = re.compile(r"\bwhere\b", re.IGNORECASE)
MKFS_RE = re.compile(r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b", re.IGNORECASE)
DD_DEVICE_WRITE_RE = re.compile(r"\bdd\b(?=.*\bof=/dev/)", re.IGNORECASE)


def claude_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude"


def hook_path(home: Path | None = None) -> Path:
    return claude_dir(home) / "hooks" / HOOK_NAME


def log_path(home: Path | None = None) -> Path:
    return claude_dir(home) / "hooks" / BLOCK_LOG


def load_payload(stdin_text: str) -> dict[str, Any]:
    if not stdin_text.strip():
        return {}
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def command_from_payload(payload: dict[str, Any]) -> str | None:
    tool_name = payload.get("tool_name") or payload.get("tool")
    if tool_name is not None and tool_name != "Bash":
        return None

    tool_input = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        return None

    command = tool_input.get("command")
    return command if isinstance(command, str) else None


def project_path_from_payload(payload: dict[str, Any]) -> str:
    for value in (
        os.environ.get("CLAUDE_PROJECT_DIR"),
        payload.get("cwd"),
        payload.get("project_dir"),
        payload.get("workspace"),
    ):
        if isinstance(value, str) and value:
            return value
    return os.getcwd()


def shell_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def has_recursive_force_rm(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if word != "rm":
            continue
        options = words[index + 1 :]
        has_recursive = False
        has_force = False
        for option in options:
            if option == "--":
                break
            if not option.startswith("-"):
                continue
            if option in {"--recursive", "--force"}:
                has_recursive = has_recursive or option == "--recursive"
                has_force = has_force or option == "--force"
                continue
            compact_flags = option.lstrip("-").lower()
            has_recursive = has_recursive or "r" in compact_flags
            has_force = has_force or "f" in compact_flags
        if has_recursive and has_force:
            return True
    return False


def has_force_push(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if word != "git":
            continue
        try:
            push_index = words.index("push", index + 1)
        except ValueError:
            continue
        flags = words[push_index + 1 :]
        return any(
            flag == "-f" or flag.startswith("--force") or flag.startswith("--force-with-lease")
            for flag in flags
        )
    return False


def has_recursive_chmod_root(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if word != "chmod":
            continue
        args = words[index + 1 :]
        has_recursive = any(arg == "-R" or (arg.startswith("-") and "r" in arg.lower()) for arg in args)
        has_mode = "777" in args
        targets_root = "/" in args
        if has_recursive and has_mode and targets_root:
            return True
    return False


def has_delete_without_where(command: str) -> bool:
    for statement in re.split(r";|\n", command):
        if DELETE_FROM_RE.search(statement) and WHERE_RE.search(statement) is None:
            return True
    return False


def blocked_reason(command: str) -> str | None:
    checks = (
        (has_recursive_force_rm, "recursive force removal is blocked"),
        (has_force_push, "force-pushing is blocked"),
        (lambda value: DROP_TABLE_RE.search(value) is not None, "DROP TABLE is blocked"),
        (lambda value: TRUNCATE_RE.search(value) is not None, "TRUNCATE is blocked"),
        (has_delete_without_where, "DELETE FROM without WHERE is blocked"),
        (lambda value: MKFS_RE.search(value) is not None, "filesystem formatting is blocked"),
        (lambda value: DD_DEVICE_WRITE_RE.search(value) is not None, "raw device writes are blocked"),
        (has_recursive_chmod_root, "recursive chmod 777 on root is blocked"),
    )
    for check, reason in checks:
        if check(command):
            return reason
    return None


def write_block_log(command: str, project_path: str, reason: str, home: Path | None = None) -> None:
    path = log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "command": command,
        "project_path": project_path,
        "reason": reason,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def run_hook(stdin_text: str) -> int:
    payload = load_payload(stdin_text)
    command = command_from_payload(payload)
    if command is None:
        return 0

    reason = blocked_reason(command)
    if reason is None:
        return 0

    project_path = project_path_from_payload(payload)
    write_block_log(command, project_path, reason)
    print(
        f"Blocked destructive Bash command: {reason}. "
        f"Review the command before running it manually: {command}",
        file=sys.stderr,
    )
    return 2


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Cannot update invalid JSON settings file: {path}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Cannot update non-object settings file: {path}")
    return data


def install(home: Path | None = None) -> Path:
    home = home or Path.home()
    target = hook_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    settings_path = claude_dir(home) / "settings.json"
    settings = load_settings(settings_path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("settings.json hooks must be an object")
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre_tool_use, list):
        raise SystemExit("settings.json hooks.PreToolUse must be a list")

    command = str(target)
    hook_entry = {"type": "command", "command": command}
    matcher_entry = {"matcher": "Bash", "hooks": [hook_entry]}

    for entry in pre_tool_use:
        if not isinstance(entry, dict) or entry.get("matcher") != "Bash":
            continue
        nested_hooks = entry.setdefault("hooks", [])
        if not isinstance(nested_hooks, list):
            raise SystemExit("Bash PreToolUse hooks must be a list")
        if hook_entry not in nested_hooks:
            nested_hooks.append(hook_entry)
        break
    else:
        pre_tool_use.append(matcher_entry)

    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="copy the hook into ~/.claude/hooks and update ~/.claude/settings.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.install:
        target = install()
        print(f"Installed destructive Bash guard hook at {target}")
        return 0
    return run_hook(sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
