#!/usr/bin/env python3
"""Static acceptance checks for the Next.js + SQLite CLAUDE.md template."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "CLAUDE.md"

REQUIRED_HEADINGS = [
    "## Stack And Versions",
    "## Default Implementation Choices",
    "## Project Structure",
    "## Dev Commands",
    "## CI And Release Gates",
    "## Environment Rules",
    "## SQLite And Migration Rules",
    "## Database Client Contracts",
    "## Naming Conventions",
    "## Data Access Patterns",
    "## App Router Patterns",
    "## Testing Expectations",
    "## Anti-Patterns",
]

REQUIRED_SIGNALS = [
    "Next.js 15",
    "App Router",
    "SQLite",
    "Turso",
    "better-sqlite3",
    "Drizzle",
    "Zod",
    "Auth.js",
    "Stripe",
    "Vitest",
    "Playwright",
    "server action",
    "foreign_keys",
    "deleted_at",
    "reason:",
]


def main() -> int:
    text = TEMPLATE.read_text(encoding="utf-8")
    missing_headings = [heading for heading in REQUIRED_HEADINGS if heading not in text]
    missing_signals = [signal for signal in REQUIRED_SIGNALS if signal not in text]

    if missing_headings or missing_signals:
        print("Template acceptance check failed.", file=sys.stderr)
        for heading in missing_headings:
            print(f"missing heading: {heading}", file=sys.stderr)
        for signal in missing_signals:
            print(f"missing signal: {signal}", file=sys.stderr)
        return 1

    print("Template acceptance check passed.")
    print(f"Checked {len(REQUIRED_HEADINGS)} required headings and {len(REQUIRED_SIGNALS)} stack/pattern signals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
