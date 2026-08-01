---
name: generate-changelog
description: Generate a structured CHANGELOG.md from git history since the latest tag.
trigger: /generate-changelog
---

# Generate Changelog

Use this skill when a repository needs a release changelog generated from git
history.

## Workflow

1. From the repository root, run:

   ```bash
   bash skills/generate-changelog/changelog.sh
   ```

2. Review `CHANGELOG.md` for project-specific wording before committing it.

3. Use stdout mode when you need a draft without writing a file:

   ```bash
   bash skills/generate-changelog/changelog.sh --stdout
   ```

The script finds commits since the latest git tag, groups them into Added,
Fixed, Changed, and Removed, and writes a formatted `CHANGELOG.md`.
