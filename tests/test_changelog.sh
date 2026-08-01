#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
script="$repo_root/skills/generate-changelog/changelog.sh"
skill="$repo_root/skills/generate-changelog/SKILL.md"

test -f "$skill"
grep -q "trigger: /generate-changelog" "$skill"
grep -q "bash skills/generate-changelog/changelog.sh" "$skill"

tmp_repo="$(mktemp -d)"
trap 'rm -rf "$tmp_repo"' EXIT

git -C "$tmp_repo" init -q
git -C "$tmp_repo" config user.email "test@example.com"
git -C "$tmp_repo" config user.name "Test User"

printf 'one\n' > "$tmp_repo/file.txt"
git -C "$tmp_repo" add file.txt
git -C "$tmp_repo" commit -q -m "chore: initial release"
git -C "$tmp_repo" tag v1.0.0

printf 'two\n' >> "$tmp_repo/file.txt"
git -C "$tmp_repo" commit -am "feat: add webhook retry queue" -q

printf 'three\n' >> "$tmp_repo/file.txt"
git -C "$tmp_repo" commit -am "fix: handle empty API responses" -q

printf 'four\n' >> "$tmp_repo/file.txt"
git -C "$tmp_repo" commit -am "docs: clarify setup steps" -q

printf 'five\n' >> "$tmp_repo/file.txt"
git -C "$tmp_repo" commit -am "remove: drop legacy config loader" -q

(cd "$tmp_repo" && bash "$script" --output CHANGELOG.md)

grep -q "Generated from git history since v1.0.0" "$tmp_repo/CHANGELOG.md"
grep -q "### Added" "$tmp_repo/CHANGELOG.md"
grep -q "feat: add webhook retry queue" "$tmp_repo/CHANGELOG.md"
grep -q "### Fixed" "$tmp_repo/CHANGELOG.md"
grep -q "fix: handle empty API responses" "$tmp_repo/CHANGELOG.md"
grep -q "### Changed" "$tmp_repo/CHANGELOG.md"
grep -q "docs: clarify setup steps" "$tmp_repo/CHANGELOG.md"
grep -q "### Removed" "$tmp_repo/CHANGELOG.md"
grep -q "remove: drop legacy config loader" "$tmp_repo/CHANGELOG.md"

echo "test_changelog.sh passed"
