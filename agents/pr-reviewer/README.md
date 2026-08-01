# Claude PR Review Agent

`claude-review` reads a GitHub pull request diff and returns a structured
Markdown review comment with a summary, risk list, improvement suggestions, and
confidence score.

## Setup

1. Add `agents/pr-reviewer/bin` to your `PATH`.
2. Run `claude-review --pr https://github.com/owner/repo/pull/123`.
3. Paste the generated Markdown into the PR after adding any project-specific test notes.

## Claude Code Sub-Agent

The companion sub-agent definition lives at `.claude/agents/pr-reviewer.md`.
Use it when you want Claude Code to run the CLI, inspect the output, and add
repository-specific context before posting a review.

## Local Diff Mode

For offline testing or CI:

```bash
claude-review --diff-file path/to/change.diff
```

## Validation

```bash
python3 -m unittest tests/test_claude_review.py -v
python3 -m py_compile agents/pr-reviewer/claude_review.py tests/test_claude_review.py
git diff --check
```
