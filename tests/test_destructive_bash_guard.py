from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "destructive-bash-guard" / "destructive_bash_guard.py"


spec = importlib.util.spec_from_file_location("destructive_bash_guard", HOOK)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DestructiveBashGuardTest(unittest.TestCase):
    def run_hook(self, payload: dict[str, object], home: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CLAUDE_PROJECT_DIR"] = "/tmp/project"
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_blocks_required_destructive_patterns_and_logs_attempts(self) -> None:
        payloads = [
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}},
            {"tool_name": "Bash", "tool_input": {"command": "sudo rm -r -f build"}},
            {"tool_name": "Bash", "tool_input": {"command": "rm -Rf build"}},
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main --force"}},
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main --force-with-lease=main"}},
            {"tool_name": "Bash", "tool_input": {"command": "git -C repo push --force"}},
            {"tool_name": "Bash", "tool_input": {"command": "psql -c 'DROP TABLE users'"}},
            {"tool_name": "Bash", "tool_input": {"command": "psql -c 'TRUNCATE audit_log'"}},
            {"tool_name": "Bash", "tool_input": {"command": "psql -c 'DELETE FROM sessions'"}},
            {
                "tool_name": "Bash",
                "tool_input": {"command": "psql -c 'DELETE FROM sessions; SELECT * FROM logs WHERE id=1'"},
            },
            {"tool_name": "Bash", "tool_input": {"command": "mkfs.ext4 /dev/sdb1"}},
            {"tool_name": "Bash", "tool_input": {"command": "dd if=image.iso of=/dev/sdb bs=4M"}},
            {"tool_name": "Bash", "tool_input": {"command": "chmod -R 777 /"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for payload in payloads:
                result = self.run_hook(payload, home)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Blocked destructive Bash command", result.stderr)

            log_entries = [
                json.loads(line)
                for line in (home / ".claude" / "hooks" / "blocked.log").read_text().splitlines()
            ]

        self.assertEqual(len(log_entries), len(payloads))
        self.assertEqual(log_entries[0]["command"], "rm -rf build")
        self.assertEqual(log_entries[0]["project_path"], "/tmp/project")
        self.assertIn("timestamp", log_entries[0])

    def test_allows_normal_commands_and_delete_with_where_clause(self) -> None:
        payloads = [
            {"tool_name": "Bash", "tool_input": {"command": "rm -r build"}},
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
            {"tool_name": "Bash", "tool_input": {"command": "psql -c 'DELETE FROM sessions WHERE id=1'"}},
            {"hook_event_name": "PreToolUse", "tool_input": {"command": "echo ok"}},
            {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for payload in payloads:
                result = self.run_hook(payload, home)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home / ".claude" / "hooks" / "blocked.log").exists())

    def test_install_copies_hook_and_merges_bash_pre_tool_use_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".claude" / "settings.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(
                json.dumps({"hooks": {"PreToolUse": [{"matcher": "Read", "hooks": []}]}}),
                encoding="utf-8",
            )

            target = guard.install(home)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertTrue(target.exists())

        self.assertEqual(target.name, "destructive-bash-guard.py")
        bash_entries = [
            entry for entry in settings["hooks"]["PreToolUse"] if entry.get("matcher") == "Bash"
        ]
        self.assertEqual(len(bash_entries), 1)
        self.assertEqual(
            bash_entries[0]["hooks"][0]["command"],
            str(target),
        )


if __name__ == "__main__":
    unittest.main()
