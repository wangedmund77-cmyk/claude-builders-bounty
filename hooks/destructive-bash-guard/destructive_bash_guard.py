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
LOG_DIR_MODE = 0o700
LOG_FILE_MODE = 0o600


class InvalidHookPayload(ValueError):
    """Raised when a non-empty hook payload cannot be trusted."""


DROP_TABLE_RE = re.compile(r"\bdrop\s+table\b", re.IGNORECASE)
DROP_DATABASE_RE = re.compile(r"\bdrop\s+database\b", re.IGNORECASE)
DROP_SCHEMA_RE = re.compile(r"\bdrop\s+schema\b", re.IGNORECASE)
TRUNCATE_RE = re.compile(r"\btruncate\b(?![-/_\w])", re.IGNORECASE)
DELETE_FROM_RE = re.compile(r"\bdelete\s+from\b", re.IGNORECASE)
UPDATE_SET_RE = re.compile(
    r"\bupdate\s+(?:only\s+)?(?:[`\"[\]\w.]+)\s+set\b",
    re.IGNORECASE,
)
WHERE_RE = re.compile(r"\bwhere\b", re.IGNORECASE)
SQL_LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")
SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
MKFS_RE = re.compile(r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b", re.IGNORECASE)
DD_DEVICE_WRITE_RE = re.compile(r"\bdd\b(?=.*\bof=/dev/)", re.IGNORECASE)
WIPEFS_RE = re.compile(r"\bwipefs\b", re.IGNORECASE)
DEVICE_REDIRECT_RE = re.compile(
    r"(?:^|\s)(?:>|>>)\s*/dev/(?:sd|hd|vd|xvd|nvme|mmcblk|disk)\S*",
    re.IGNORECASE,
)
DEV_TCP_RE = re.compile(r"/dev/(?:tcp|udp)/[^/\s]+/\d+", re.IGNORECASE)
SHELL_INTERACTIVE_RE = re.compile(
    r"\b(?:bash|dash|fish|ksh|sh|zsh)\b\s+[^;&|]*-i\b",
    re.IGNORECASE,
)
PYTHON_REVERSE_SHELL_RE = re.compile(
    r"\bsocket\b.*\bconnect\s*\(.*\bdup2\s*\(.*(?:/bin/(?:ba)?sh|pty\.spawn)",
    re.IGNORECASE | re.DOTALL,
)
SQL_STATEMENT_START_RE = re.compile(
    r"\b(select|insert|update|delete|drop|truncate|create|alter|merge)\b",
    re.IGNORECASE,
)
BASH_FUNCTION_NAME = r"[A-Za-z_:.][A-Za-z0-9_:.]*"
BASH_FUNCTION_DEFINITION_RES = (
    re.compile(
        rf"(?P<name>{BASH_FUNCTION_NAME})\s*\(\)\s*\{{(?P<body>.*?)\}}\s*;?\s*(?P=name)(?=$|[\s;])",
        re.DOTALL,
    ),
    re.compile(
        rf"function\s+(?P<name>{BASH_FUNCTION_NAME})\s*\{{(?P<body>.*?)\}}\s*;?\s*(?P=name)(?=$|[\s;])",
        re.DOTALL,
    ),
)
REMOTE_SCRIPT_FETCHERS = {"curl", "wget"}
NETCAT_EXECUTABLES = {"nc", "ncat", "netcat"}
NETCAT_EXEC_FLAGS = {"-e", "-c", "--exec", "--sh-exec"}
SHELL_COMMAND_PREFIXES = {"command", "env", "sudo"}
SHELL_NAMES = {"bash", "dash", "fish", "ksh", "sh", "zsh"}
SYSTEM_POWER_COMMANDS = {"halt", "poweroff", "reboot", "shutdown"}
SYSTEMCTL_POWER_ACTIONS = {
    "halt",
    "hibernate",
    "hybrid-sleep",
    "poweroff",
    "reboot",
    "suspend",
}
TEXT_ONLY_EXECUTABLES = {
    "awk",
    "cat",
    "echo",
    "egrep",
    "fgrep",
    "grep",
    "head",
    "less",
    "more",
    "printf",
    "rg",
    "sed",
    "tail",
}
PREFIX_OPTIONS_WITH_VALUE = {
    "env": {"-u", "--unset", "-C", "--chdir"},
    "sudo": {
        "-C",
        "--close-from",
        "-g",
        "--group",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-T",
        "--command-timeout",
        "-u",
        "--user",
    },
}
GIT_FALSE_VALUES = {"0", "false", "no", "off", "n"}
SHELL_EXECUTABLES = {"bash", "dash", "fish", "ksh", "sh", "zsh"}
COMMAND_SEPARATORS = {";", "&&", "||"}
PIPE_OPERATORS = {"|", "|&"}
REDIRECT_OPERATORS = {">", ">>", "<", "<<"}


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
    except json.JSONDecodeError as exc:
        raise InvalidHookPayload("invalid hook JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidHookPayload("hook payload must be a JSON object")
    return payload


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


def shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return shell_words(command)


def executable_name(words: list[str]) -> str | None:
    index = 0
    while index < len(words):
        name = Path(words[index]).name
        if name not in SHELL_COMMAND_PREFIXES:
            break
        index += 1
        options_with_value = PREFIX_OPTIONS_WITH_VALUE.get(name, set())
        while index < len(words) and words[index].startswith("-"):
            option = words[index]
            index += 1
            option_name = option.split("=", 1)[0]
            if option_name in options_with_value and "=" not in option and index < len(words):
                index += 1
        while index < len(words) and "=" in words[index] and not words[index].startswith("-"):
            index += 1
    if index >= len(words):
        return None
    return Path(words[index]).name


def has_recursive_force_rm(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "rm":
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
        if Path(word).name != "git":
            continue
        try:
            push_index = words.index("push", index + 1)
        except ValueError:
            continue
        git_options = words[index + 1 : push_index]
        for option_index, option in enumerate(git_options):
            if option != "-c" or option_index + 1 >= len(git_options):
                continue
            config = git_options[option_index + 1]
            if not config.lower().startswith("push.force"):
                continue
            value = config.split("=", 1)[1].strip().lower() if "=" in config else "true"
            if value not in GIT_FALSE_VALUES:
                return True
        flags = words[push_index + 1 :]
        return any(
            flag == "-f"
            or flag.startswith("--force")
            or flag.startswith("--force-with-lease")
            or flag.startswith("+")
            for flag in flags
        )
    return False


def is_plain_text_mention(command: str) -> bool:
    tokens = shell_tokens(command)
    if any(token in COMMAND_SEPARATORS | PIPE_OPERATORS | REDIRECT_OPERATORS for token in tokens):
        return False
    return executable_name(tokens) in TEXT_ONLY_EXECUTABLES


def has_hard_git_reset(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            reset_index = words.index("reset", index + 1)
        except ValueError:
            continue
        if any(flag == "--hard" or flag.startswith("--hard=") for flag in words[reset_index + 1 :]):
            return True
    return False


def has_forced_git_clean(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            clean_index = words.index("clean", index + 1)
        except ValueError:
            continue
        args = words[clean_index + 1 :]
        has_dry_run = any(
            arg in {"-n", "--dry-run"} or (arg.startswith("-") and "n" in arg.lstrip("-"))
            for arg in args
        )
        if has_dry_run:
            continue
        if any(
            arg == "--force" or arg.startswith("--force=") or (arg.startswith("-") and "f" in arg)
            for arg in args
        ):
            return True
    return False


def has_worktree_git_checkout(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            checkout_index = words.index("checkout", index + 1)
        except ValueError:
            continue
        args = words[checkout_index + 1 :]
        if "--" in args and args.index("--") + 1 < len(args):
            return True
    return False


def restore_has_worktree_flag(args: list[str]) -> bool:
    return any(
        arg == "--worktree"
        or arg == "-W"
        or (arg.startswith("-") and not arg.startswith("--") and "W" in arg[1:])
        for arg in args
    )


def restore_has_staged_flag(args: list[str]) -> bool:
    return any(
        arg == "--staged"
        or arg == "-S"
        or (arg.startswith("-") and not arg.startswith("--") and "S" in arg[1:])
        for arg in args
    )


def restore_has_pathspec(args: list[str]) -> bool:
    options_with_value = {"--source", "-s", "--pathspec-from-file"}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return index + 1 < len(args)
        if arg in options_with_value:
            index += 2
            continue
        if arg.startswith("--source=") or arg.startswith("--pathspec-from-file="):
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return True
    return False


def has_worktree_git_restore(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            restore_index = words.index("restore", index + 1)
        except ValueError:
            continue
        args = words[restore_index + 1 :]
        if restore_has_staged_flag(args) and not restore_has_worktree_flag(args):
            continue
        if restore_has_pathspec(args):
            return True
    return False


def has_forced_branch_delete(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            branch_index = words.index("branch", index + 1)
        except ValueError:
            continue
        args = words[branch_index + 1 :]
        if any(
            arg == "-D" or (arg.startswith("-") and not arg.startswith("--") and "D" in arg[1:])
            for arg in args
        ):
            return True
        has_delete = any(arg in {"-d", "--delete"} for arg in args)
        has_force = any(arg in {"-f", "--force"} for arg in args)
        if has_delete and has_force:
            return True
    return False


def has_stash_drop_or_clear(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "git":
            continue
        try:
            stash_index = words.index("stash", index + 1)
        except ValueError:
            continue
        args = [arg for arg in words[stash_index + 1 :] if not arg.startswith("-")]
        if args and args[0] in {"clear", "drop"}:
            return True
    return False


CRITICAL_RECURSIVE_TARGETS = {"/", "~", "$HOME", "${HOME}"}
DANGEROUS_CHMOD_MODES = {"000", "0000", "777", "0777"}


def has_recursive_chmod_dangerous_target(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "chmod":
            continue
        args = words[index + 1 :]
        has_recursive = any(arg == "-R" or (arg.startswith("-") and "r" in arg.lower()) for arg in args)
        has_mode = any(arg in DANGEROUS_CHMOD_MODES for arg in args)
        has_target = any(arg in CRITICAL_RECURSIVE_TARGETS for arg in args)
        if has_recursive and has_mode and has_target:
            return True
    return False


def has_recursive_ownership_dangerous_target(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name not in {"chown", "chgrp"}:
            continue
        args = words[index + 1 :]
        has_recursive = any(
            arg == "-R" or arg == "--recursive" or (arg.startswith("-") and "r" in arg.lower())
            for arg in args
        )
        has_target = any(arg in CRITICAL_RECURSIVE_TARGETS for arg in args)
        if has_recursive and has_target:
            return True
    return False


def has_find_delete_dangerous_target(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "find":
            continue
        args = words[index + 1 :]
        has_critical_target = any(arg in CRITICAL_RECURSIVE_TARGETS for arg in args)
        has_delete_action = any(arg == "-delete" for arg in args)
        if has_critical_target and has_delete_action:
            return True
    return False


def has_shred(command: str) -> bool:
    return executable_name(shell_words(command)) == "shred"


def has_system_power_action(command: str) -> bool:
    words = shell_words(command)
    name = executable_name(words)
    if name in SYSTEM_POWER_COMMANDS:
        return True
    if name != "systemctl":
        return False
    try:
        systemctl_index = next(
            index for index, word in enumerate(words) if Path(word).name == "systemctl"
        )
    except StopIteration:
        return False
    return any(arg in SYSTEMCTL_POWER_ACTIONS for arg in words[systemctl_index + 1 :])


def has_shell_fork_bomb(command: str) -> bool:
    for function_definition_re in BASH_FUNCTION_DEFINITION_RES:
        for match in function_definition_re.finditer(command):
            name = re.escape(match.group("name"))
            body = match.group("body")
            if re.search(rf"{name}\s*\|\s*{name}\s*&", body):
                return True
    return False


def command_groups(tokens: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            if current:
                groups.append(current)
            current = []
            continue
        current.append(token)
    if current:
        groups.append(current)
    return groups


def pipeline_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in PIPE_OPERATORS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def has_remote_fetch_to_shell(command: str) -> bool:
    for group in command_groups(shell_tokens(command)):
        seen_remote_fetcher = False
        for segment in pipeline_segments(group):
            name = executable_name(segment)
            if seen_remote_fetcher and name in SHELL_EXECUTABLES:
                return True
            if name in REMOTE_SCRIPT_FETCHERS:
                seen_remote_fetcher = True
    return False


def has_netcat_exec_shell(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name not in NETCAT_EXECUTABLES:
            continue
        args = words[index + 1 :]
        for arg_index, arg in enumerate(args):
            if arg in NETCAT_EXEC_FLAGS:
                return True
            if arg.startswith("--exec=") or arg.startswith("--sh-exec="):
                return True
            if arg == "-U":
                continue
            if arg in SHELL_NAMES or arg.endswith(("/sh", "/bash", "/zsh")):
                previous = args[arg_index - 1] if arg_index else ""
                if previous in NETCAT_EXEC_FLAGS:
                    return True
    return False


def has_socat_exec_shell(command: str) -> bool:
    words = shell_words(command)
    for index, word in enumerate(words):
        if Path(word).name != "socat":
            continue
        args = [arg.lower() for arg in words[index + 1 :]]
        has_network_endpoint = any(
            arg.startswith(("tcp:", "tcp4:", "tcp6:", "tcp-connect:", "openssl:")) for arg in args
        )
        has_shell_exec = any(
            arg.startswith(("exec:", "system:")) and any(shell in arg for shell in ("/sh", "/bash", "/zsh"))
            for arg in args
        )
        if has_network_endpoint and has_shell_exec:
            return True
    return False


def has_mkfifo_netcat_shell(command: str) -> bool:
    words = shell_words(command)
    has_mkfifo = any(Path(word).name == "mkfifo" for word in words)
    has_netcat = any(Path(word).name in NETCAT_EXECUTABLES for word in words)
    if not has_mkfifo or not has_netcat:
        return False
    return any(shell in command for shell in ("/bin/sh", "/bin/bash", " sh -i", " bash -i"))


def has_dev_tcp_reverse_shell(command: str) -> bool:
    if DEV_TCP_RE.search(command) is None:
        return False
    if SHELL_INTERACTIVE_RE.search(command):
        return True
    return any(marker in command for marker in (">&", "0>&1", "1>&", "2>&1", "<>", "exec "))


def has_python_reverse_shell(command: str) -> bool:
    words = shell_words(command)
    if not any(Path(word).name.startswith("python") for word in words):
        return False
    return PYTHON_REVERSE_SHELL_RE.search(command) is not None


def has_reverse_shell(command: str) -> bool:
    return any(
        check(command)
        for check in (
            has_dev_tcp_reverse_shell,
            has_netcat_exec_shell,
            has_socat_exec_shell,
            has_mkfifo_netcat_shell,
            has_python_reverse_shell,
        )
    )


def strip_sql_comments(command: str) -> str:
    command = SQL_BLOCK_COMMENT_RE.sub("", command)
    return SQL_LINE_COMMENT_RE.sub("", command)


def delete_statement_has_where(statement: str, match: re.Match[str]) -> bool:
    remainder = statement[match.end() :]
    where_match = WHERE_RE.search(remainder)
    if where_match is None:
        return False
    before_where = remainder[: where_match.start()]
    return SQL_STATEMENT_START_RE.search(before_where) is None


def update_statement_has_where(statement: str, match: re.Match[str]) -> bool:
    remainder = statement[match.end() :]
    where_match = WHERE_RE.search(remainder)
    if where_match is None:
        return False
    before_where = remainder[: where_match.start()]
    return SQL_STATEMENT_START_RE.search(before_where) is None


def has_delete_without_where(command: str) -> bool:
    if is_plain_text_mention(command):
        return False
    for statement in strip_sql_comments(command).split(";"):
        for match in DELETE_FROM_RE.finditer(statement):
            if not delete_statement_has_where(statement, match):
                return True
    return False


def has_update_without_where(command: str) -> bool:
    if is_plain_text_mention(command):
        return False
    for statement in strip_sql_comments(command).split(";"):
        for match in UPDATE_SET_RE.finditer(statement):
            if not update_statement_has_where(statement, match):
                return True
    return False


def has_sql_truncate(command: str) -> bool:
    if is_plain_text_mention(command):
        return False
    words = shell_words(command)
    if executable_name(words) == "truncate":
        return False
    return TRUNCATE_RE.search(command) is not None


def has_drop_table(command: str) -> bool:
    return not is_plain_text_mention(command) and DROP_TABLE_RE.search(command) is not None


def has_drop_database(command: str) -> bool:
    return not is_plain_text_mention(command) and DROP_DATABASE_RE.search(command) is not None


def has_drop_schema(command: str) -> bool:
    return not is_plain_text_mention(command) and DROP_SCHEMA_RE.search(command) is not None


def nested_shell_commands(command: str) -> list[str]:
    words = shell_words(command)
    nested: list[str] = []
    for index, word in enumerate(words):
        if Path(word).name not in SHELL_EXECUTABLES:
            continue
        args = words[index + 1 :]
        for arg_index, arg in enumerate(args):
            if arg == "-c" and arg_index + 1 < len(args):
                nested.append(args[arg_index + 1])
                break
            if arg.startswith("-") and "c" in arg[1:] and arg_index + 1 < len(args):
                nested.append(args[arg_index + 1])
                break
    return nested


def nested_shell_blocked_reason(command: str, depth: int) -> str | None:
    if depth >= 2:
        return None
    for nested_command in nested_shell_commands(command):
        reason = blocked_reason(nested_command, depth + 1)
        if reason is not None:
            return f"nested shell command: {reason}"
    return None


def blocked_reason(command: str, depth: int = 0) -> str | None:
    if is_plain_text_mention(command):
        return None

    checks = (
        (has_recursive_force_rm, "recursive force removal is blocked"),
        (has_force_push, "force-pushing is blocked"),
        (has_hard_git_reset, "git reset --hard is blocked"),
        (has_forced_git_clean, "forced git clean is blocked"),
        (has_worktree_git_checkout, "git checkout path restore is blocked"),
        (has_worktree_git_restore, "git restore of worktree files is blocked"),
        (has_forced_branch_delete, "forced git branch deletion is blocked"),
        (has_stash_drop_or_clear, "git stash deletion is blocked"),
        (has_drop_table, "DROP TABLE is blocked"),
        (has_drop_database, "DROP DATABASE is blocked"),
        (has_drop_schema, "DROP SCHEMA is blocked"),
        (has_sql_truncate, "TRUNCATE is blocked"),
        (has_delete_without_where, "DELETE FROM without WHERE is blocked"),
        (has_update_without_where, "UPDATE without WHERE is blocked"),
        (lambda value: MKFS_RE.search(value) is not None, "filesystem formatting is blocked"),
        (lambda value: DD_DEVICE_WRITE_RE.search(value) is not None, "raw device writes are blocked"),
        (lambda value: WIPEFS_RE.search(value) is not None, "filesystem signature wiping is blocked"),
        (lambda value: DEVICE_REDIRECT_RE.search(value) is not None, "raw device redirects are blocked"),
        (has_shred, "irreversible file shredding is blocked"),
        (has_system_power_action, "system power actions are blocked"),
        (has_recursive_chmod_dangerous_target, "recursive chmod on critical paths is blocked"),
        (has_recursive_ownership_dangerous_target, "recursive ownership changes on critical paths are blocked"),
        (has_find_delete_dangerous_target, "find -delete on critical paths is blocked"),
        (has_shell_fork_bomb, "shell fork bomb is blocked"),
        (has_reverse_shell, "reverse-shell launch patterns are blocked"),
        (has_remote_fetch_to_shell, "remote script piped to shell is blocked"),
    )
    for check, reason in checks:
        if check(command):
            return reason
    return nested_shell_blocked_reason(command, depth)


def write_block_log(command: str, project_path: str, reason: str, home: Path | None = None) -> None:
    path = log_path(home)
    path.parent.mkdir(parents=True, mode=LOG_DIR_MODE, exist_ok=True)
    path.parent.chmod(LOG_DIR_MODE)
    if path.is_symlink():
        raise OSError(f"refusing to write block log through symlink: {path}")

    entry = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "command": command,
        "project_path": project_path,
        "reason": reason,
    }

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, LOG_FILE_MODE)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        if hasattr(os, "fchmod"):
            os.fchmod(handle.fileno(), LOG_FILE_MODE)
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def block_message(command: str, reason: str, log_warning: str = "") -> str:
    return (
        f"Blocked destructive Bash command: {reason}. "
        f"Review the command before running it manually: {command}.{log_warning}"
    )


def invalid_payload_message(reason: str, log_warning: str = "") -> str:
    return f"Blocked Bash hook payload because it could not be trusted: {reason}.{log_warning}"


def deny_payload(message: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }


def run_hook(stdin_text: str) -> int:
    try:
        payload = load_payload(stdin_text)
    except InvalidHookPayload as exc:
        reason = str(exc)
        log_warning = ""
        try:
            write_block_log("<invalid hook payload>", os.getcwd(), reason)
        except OSError as log_exc:
            log_warning = f" Block log was not written: {log_exc}."
        print(json.dumps(deny_payload(invalid_payload_message(reason, log_warning)), sort_keys=True))
        return 0

    command = command_from_payload(payload)
    if command is None:
        return 0

    reason = blocked_reason(command)
    if reason is None:
        return 0

    project_path = project_path_from_payload(payload)
    log_warning = ""
    try:
        write_block_log(command, project_path, reason)
    except OSError as exc:
        log_warning = f" Block log was not written: {exc}."
    print(json.dumps(deny_payload(block_message(command, reason, log_warning)), sort_keys=True))
    return 0


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
