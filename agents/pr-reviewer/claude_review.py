#!/usr/bin/env python3
"""Generate a structured Markdown review for a GitHub pull request diff."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


PR_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$")
RISK_PATTERNS = [
    ("Shell execution", re.compile(r"\b(subprocess\.[^(]+\(.*shell\s*=\s*True|os\.system\(|exec\(|eval\()")),
    ("Destructive command", re.compile(r"\brm\s+-[^\n]*r[^\n]*f\b")),
    ("Credential handling", re.compile(r"\b(secret|token|password|api[_-]?key)\b", re.I)),
    ("Permissive CORS", re.compile(r"Access-Control-Allow-Origin['\"]?\s*[:=]\s*['\"]\*")),
    ("Database mutation", re.compile(r"\b(delete\s+from|update\s+\w+\s+set)\b(?![^;\n]*\bwhere\b)", re.I)),
]


@dataclass
class FileChange:
    path: str
    additions: int = 0
    deletions: int = 0
    risky_lines: list[str] = field(default_factory=list)


@dataclass
class ReviewAnalysis:
    files: list[FileChange]
    total_additions: int
    total_deletions: int
    risks: list[str]
    suggestions: list[str]
    confidence: str


def pr_to_diff_url(pr_url: str) -> str:
    match = PR_RE.match(pr_url)
    if not match:
        raise ValueError("expected a GitHub pull request URL, for example https://github.com/owner/repo/pull/123")
    owner, repo, number = match.groups()
    return f"https://github.com/{owner}/{repo}/pull/{number}.diff"


def fetch_pr_diff(pr_url: str) -> str:
    request = urllib.request.Request(
        pr_to_diff_url(pr_url),
        headers={"User-Agent": "claude-review-agent"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub returned HTTP {exc.code} while fetching PR diff") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not fetch PR diff: {exc.reason}") from exc


def parse_diff(diff_text: str) -> list[FileChange]:
    files: list[FileChange] = []
    current: FileChange | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.*?) b/(.*)", line)
            path = match.group(2) if match else line.rsplit(" ", 1)[-1].removeprefix("b/")
            current = FileChange(path=path)
            files.append(current)
            continue

        if current is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current.additions += 1
            added = line[1:]
            for label, pattern in RISK_PATTERNS:
                if pattern.search(added):
                    current.risky_lines.append(f"{label}: `{added.strip()[:140]}`")
        elif line.startswith("-") and not line.startswith("---"):
            current.deletions += 1

    return files


def analyze_diff(diff_text: str) -> ReviewAnalysis:
    files = parse_diff(diff_text)
    total_additions = sum(file.additions for file in files)
    total_deletions = sum(file.deletions for file in files)
    risks: list[str] = []
    suggestions: list[str] = []

    if not files:
        risks.append("The diff appears to be empty or could not be parsed.")
        suggestions.append("Confirm the PR branch contains committed changes before review.")

    for file in files:
        lowered = file.path.lower()
        if file.risky_lines:
            risks.extend(f"{file.path}: {line}" for line in file.risky_lines[:3])
        if any(part in lowered for part in ("auth", "security", "permission", "payment", "secret")):
            risks.append(f"{file.path}: touches a security-sensitive area and needs focused regression coverage.")
        if lowered.endswith(("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "package.json")):
            risks.append(f"{file.path}: dependency or package metadata changed; verify install and supply-chain impact.")
        if ".github/workflows/" in lowered:
            risks.append(f"{file.path}: CI workflow changed; verify permissions and trigger scope are minimal.")
        if "migration" in lowered or lowered.endswith(".sql"):
            risks.append(f"{file.path}: database schema or migration logic changed; verify rollback and idempotency.")

    if total_additions + total_deletions > 800:
        risks.append("Large diff size increases review risk; split or add focused test evidence if possible.")
    elif not risks:
        risks.append("No obvious high-risk patterns were detected in the added lines.")

    if not any("test" in file.path.lower() for file in files):
        suggestions.append("Add or reference targeted tests for the changed behavior.")
    if any(file.risky_lines for file in files):
        suggestions.append("Document why flagged risky lines are safe, or replace them with narrower helpers.")
    if any(".github/workflows/" in file.path.lower() for file in files):
        suggestions.append("Pin workflow permissions and include a dry-run or workflow-dispatch validation note.")
    if any(file.path.lower().endswith((".md", ".mdx", ".rst")) for file in files):
        suggestions.append("Preview the rendered documentation to catch broken links, formatting, or stale examples.")
    if not suggestions:
        suggestions.append("Include exact validation commands in the PR description for reviewer reproducibility.")

    confidence = "High"
    if total_additions + total_deletions > 800 or any(file.risky_lines for file in files):
        confidence = "Medium"
    if not files or total_additions + total_deletions > 2000:
        confidence = "Low"

    return ReviewAnalysis(files, total_additions, total_deletions, risks, suggestions, confidence)


def render_markdown(analysis: ReviewAnalysis, pr_url: str | None = None) -> str:
    changed = ", ".join(file.path for file in analysis.files[:5])
    if len(analysis.files) > 5:
        changed += f", and {len(analysis.files) - 5} more"
    changed = changed or "no parsed files"

    lines = [
        "## PR Review",
        "",
        "### Summary of changes",
        "",
        (
            f"This PR changes {len(analysis.files)} file(s): {changed}. "
            f"The parsed diff contains {analysis.total_additions} additions and "
            f"{analysis.total_deletions} deletions."
        ),
        (
            "The review below is generated from the pull request diff and should be "
            "combined with project-specific test results before merge."
        ),
        "",
        "### Identified risks",
        "",
    ]
    lines.extend(f"- {risk}" for risk in analysis.risks)
    lines.extend(["", "### Improvement suggestions", ""])
    lines.extend(f"- {suggestion}" for suggestion in analysis.suggestions)
    lines.extend(["", f"### Confidence score: {analysis.confidence}"])
    if pr_url:
        lines.extend(["", f"_Reviewed PR: {pr_url}_"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a structured Markdown PR review comment.")
    parser.add_argument("--pr", help="GitHub pull request URL to fetch and review")
    parser.add_argument("--diff-file", help="Local unified diff file to review, useful for tests")
    args = parser.parse_args(argv)

    if bool(args.pr) == bool(args.diff_file):
        parser.error("provide exactly one of --pr or --diff-file")

    try:
        if args.pr:
            diff_text = fetch_pr_diff(args.pr)
            pr_url = args.pr
        else:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
            pr_url = None
        print(render_markdown(analyze_diff(diff_text), pr_url=pr_url))
    except Exception as exc:  # noqa: BLE001 - CLI error boundary
        print(f"claude-review: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
