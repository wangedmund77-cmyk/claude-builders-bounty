#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash changelog.sh [--output CHANGELOG.md] [--stdout]

Generates a Keep a Changelog-style CHANGELOG.md from commits since the most
recent git tag. If the repository has no tags, all commits are included.
USAGE
}

output_file="CHANGELOG.md"
write_stdout=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      output_file="${2:-}"
      if [[ -z "$output_file" ]]; then
        echo "error: --output requires a path" >&2
        exit 2
      fi
      shift 2
      ;;
    --stdout)
      write_stdout=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: changelog.sh must be run inside a git repository" >&2
  exit 1
fi

last_tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [[ -n "$last_tag" ]]; then
  range="${last_tag}..HEAD"
  range_label="since ${last_tag}"
else
  range="HEAD"
  range_label="from initial commit"
fi

commit_lines="$(git log --reverse --pretty=format:'%s%x1f%h' "$range")"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

touch "$tmp_dir/added" "$tmp_dir/fixed" "$tmp_dir/changed" "$tmp_dir/removed"

categorize_subject() {
  local subject="$1"
  local normalized
  normalized="$(printf '%s' "$subject" | tr '[:upper:]' '[:lower:]')"

  case "$normalized" in
    feat:*|feat\(*|add:*|added:*|create:*|implement:*)
      echo "added"
      ;;
    fix:*|fix\(*|bug:*|bugfix:*|hotfix:*|repair:*)
      echo "fixed"
      ;;
    remove:*|removed:*|delete:*|deleted:*|drop:*|dropped:*|deprecate:*)
      echo "removed"
      ;;
    *)
      echo "changed"
      ;;
  esac
}

if [[ -n "$commit_lines" ]]; then
  while IFS=$'\x1f' read -r subject hash; do
    [[ -z "$subject" ]] && continue
    category="$(categorize_subject "$subject")"
    printf -- '- %s (%s)\n' "$subject" "$hash" >> "$tmp_dir/$category"
  done <<< "$commit_lines"
fi

render_section() {
  local title="$1"
  local file="$2"

  printf '### %s\n\n' "$title"
  if [[ -s "$file" ]]; then
    cat "$file"
  else
    printf -- '- No changes.\n'
  fi
  printf '\n'
}

{
  printf '# Changelog\n\n'
  printf '## Unreleased - %s\n\n' "$(date -u +%Y-%m-%d)"
  printf '_Generated from git history %s._\n\n' "$range_label"
  render_section "Added" "$tmp_dir/added"
  render_section "Fixed" "$tmp_dir/fixed"
  render_section "Changed" "$tmp_dir/changed"
  render_section "Removed" "$tmp_dir/removed"
} > "$tmp_dir/CHANGELOG.md"

if [[ "$write_stdout" -eq 1 ]]; then
  cat "$tmp_dir/CHANGELOG.md"
else
  cp "$tmp_dir/CHANGELOG.md" "$output_file"
  echo "Wrote $output_file"
fi
