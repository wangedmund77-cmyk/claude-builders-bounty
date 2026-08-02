#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash changelog.sh [--repo PATH] [--since REF] [--version VERSION] [--output CHANGELOG.md] [--stdout]

Generates a Keep a Changelog-style CHANGELOG.md from commits since the most
recent git tag, or since an explicit --since ref. If no tag exists, all commits
are included.
USAGE
}

repo_path="."
since_ref=""
version="Unreleased"
output_file="CHANGELOG.md"
write_stdout=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo_path="${2:-}"
      if [[ -z "$repo_path" ]]; then
        echo "error: --repo requires a path" >&2
        exit 2
      fi
      shift 2
      ;;
    --since)
      since_ref="${2:-}"
      if [[ -z "$since_ref" ]]; then
        echo "error: --since requires a git ref" >&2
        exit 2
      fi
      shift 2
      ;;
    --version)
      version="${2:-}"
      if [[ -z "$version" ]]; then
        echo "error: --version requires a heading value" >&2
        exit 2
      fi
      shift 2
      ;;
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

if ! repo_root="$(git -C "$repo_path" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: --repo must point inside a git repository" >&2
  exit 1
fi

if [[ -n "$since_ref" ]]; then
  if ! git -C "$repo_root" rev-parse --verify --quiet "${since_ref}^{commit}" >/dev/null; then
    echo "error: --since ref not found: $since_ref" >&2
    exit 1
  fi
  range="${since_ref}..HEAD"
  range_label="since ${since_ref}"
else
  last_tag="$(git -C "$repo_root" describe --tags --abbrev=0 2>/dev/null || true)"
  if [[ -n "$last_tag" ]]; then
    range="${last_tag}..HEAD"
    range_label="since ${last_tag}"
  else
    range="HEAD"
    range_label="from initial commit"
  fi
fi

commit_lines="$(git -C "$repo_root" log --reverse --pretty=format:'%s%x1f%h' "$range")"

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
  printf '## %s - %s\n\n' "$version" "$(date -u +%Y-%m-%d)"
  printf '_Generated from git history %s._\n\n' "$range_label"
  render_section "Added" "$tmp_dir/added"
  render_section "Fixed" "$tmp_dir/fixed"
  render_section "Changed" "$tmp_dir/changed"
  render_section "Removed" "$tmp_dir/removed"
} > "$tmp_dir/CHANGELOG.md"

if [[ "$write_stdout" -eq 1 ]]; then
  cat "$tmp_dir/CHANGELOG.md"
else
  if [[ "$output_file" = /* ]]; then
    output_path="$output_file"
  else
    output_path="$repo_root/$output_file"
  fi
  mkdir -p "$(dirname "$output_path")"
  cp "$tmp_dir/CHANGELOG.md" "$output_path"
  echo "Wrote $output_path"
fi
