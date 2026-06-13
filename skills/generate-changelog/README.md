# Generate Changelog

Create a structured `CHANGELOG.md` from the current repository's git history.

## Setup

1. Copy `changelog.sh` into the root of any git repository.
2. Run `bash changelog.sh`.
3. Review the generated `CHANGELOG.md` before committing it.

## Behavior

The script finds the most recent git tag and includes commits from that tag to
`HEAD`. If no tag exists, it includes the full history. Commit subjects are
grouped into `Added`, `Fixed`, `Changed`, and `Removed` using common commit
prefixes such as `feat:`, `fix:`, `remove:`, and `docs:`.

Use `--stdout` to preview without writing a file:

```bash
bash changelog.sh --stdout
```

Use `--output` to choose a custom path:

```bash
bash changelog.sh --output docs/CHANGELOG.md
```
