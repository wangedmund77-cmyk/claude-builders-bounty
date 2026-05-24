# Next.js 15 + SQLite SaaS CLAUDE.md Template

This folder contains an opinionated `CLAUDE.md` for a greenfield SaaS project
using Next.js 15 App Router, TypeScript, SQLite, and server-first React.

## Files

- `CLAUDE.md`: the template to copy into a project root.
- `GREENFIELD_TEST_NOTES.md`: smoke-test notes for checking whether Claude Code
  understands the template without extra clarification.

## Setup

1. Create or open a Next.js 15 App Router SaaS project.
2. Copy `CLAUDE.md` into the project root.
3. Keep the script names from the template, or map them to the project's package
   manager in `package.json`.
4. Start Claude Code from the project root so the file is loaded before work
   begins.

## What It Covers

- Stack and version assumptions.
- Folder structure and naming conventions.
- SQLite, Turso, and migration rules.
- Data-access and server-action patterns.
- Auth, tenancy, permissions, billing, and webhook rules.
- Testing expectations and deployment notes.
- Anti-patterns to avoid, with a reason for each rule.

## Acceptance-Criteria Mapping

| Issue requirement | Covered in |
| --- | --- |
| Project structure | `Project Structure`, `Naming Conventions` |
| DB migration rules | `SQLite And Migration Rules` |
| Dev commands | `Dev Commands` |
| Patterns to follow | `Data Access Patterns`, `App Router Patterns`, `Component Patterns` |
| Anti-patterns to avoid | `Anti-Patterns` |
| Opinionated reasons | Every major rule includes a `reason:` clause |
| Greenfield usability | `Greenfield Smoke Prompt`, `GREENFIELD_TEST_NOTES.md` |
