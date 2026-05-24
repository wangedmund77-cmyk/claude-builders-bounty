# CLAUDE.md

This project is a production-minded SaaS app built with Next.js 15 App Router,
TypeScript, SQLite, and server-first React. Follow these rules unless a human
explicitly changes the architecture.

## Stack And Versions

- Use Next.js 15 with the App Router in `app/`; reason: routing, data loading,
  metadata, and server actions should live in the same convention-driven tree.
- Use TypeScript in strict mode; reason: SaaS billing, auth, and data workflows
  need compile-time checks before users touch them.
- Use SQLite through `better-sqlite3` for local/single-node deployments or Turso
  for hosted/libSQL deployments; reason: both keep the SQL model explicit and
  avoid a heavy ORM for a small SaaS.
- Use React Server Components by default; reason: secrets, database access, and
  authorization checks belong on the server.
- Use Tailwind or CSS modules for styling, but keep business state out of CSS;
  reason: UI styling should not hide data or permission logic.

## Project Structure

```text
app/
  (marketing)/              Public pages and pricing copy.
  (app)/                    Authenticated product surface.
  api/                      Route handlers for webhooks and external clients.
  actions/                  Server actions grouped by domain.
components/
  ui/                       Reusable presentational primitives.
  forms/                    Client form shells only when interactivity is needed.
db/
  client.ts                 Database connection factory.
  schema.sql                Canonical schema for fresh installs.
  migrations/               Numbered forward-only SQL migrations.
  queries/                  Typed query helpers by aggregate/root concept.
lib/
  auth.ts                   Session and user lookup helpers.
  env.ts                    Runtime env validation.
  permissions.ts            Role and ownership checks.
  validators/               Zod schemas shared by forms and actions.
tests/
  unit/                     Pure functions and validators.
  integration/              DB-backed actions and route handlers.
  e2e/                      Critical user paths.
```

Reason: folders follow runtime boundaries. Server-only code stays in `db/` and
`lib/`; UI composition stays in `app/` and `components/`; domain mutations live
in `app/actions/` where App Router expects them.

## Dev Commands

- `npm run dev`: start the app locally.
- `npm run lint`: run ESLint and framework lint checks.
- `npm run typecheck`: run `tsc --noEmit`.
- `npm run test`: run unit and integration tests.
- `npm run test:e2e`: run browser tests for signup, login, billing, and the main
  paid workflow.
- `npm run db:migrate`: apply pending SQL migrations.
- `npm run db:reset`: rebuild the local SQLite database from schema plus
  migrations.

Reason: every PR should prove type safety, lint cleanliness, and database
compatibility without relying on a deployed environment.

## Environment Rules

- Read environment variables only from `lib/env.ts`; reason: validation,
  defaults, and error messages should be centralized.
- Never read `process.env` in client components; reason: client bundles must not
  leak secrets.
- Required variables should fail fast during server startup or first server
  action call; reason: misconfigured billing/auth should not fail halfway through
  a user flow.
- Keep `.env.example` current whenever env requirements change; reason: new
  deployments should be reproducible.

## SQLite And Migration Rules

- Write migrations as numbered SQL files, for example
  `db/migrations/0007_add_team_members.sql`; reason: review order and production
  rollout order must be obvious.
- Migrations are forward-only. Do not edit a migration after it has shipped;
  reason: deployed databases may already have applied it.
- Every table must include a stable text primary key or integer primary key,
  `created_at`, and `updated_at` where updates are possible; reason: SaaS audit
  and support workflows depend on timestamps.
- Use foreign keys and enable `PRAGMA foreign_keys = ON` when opening SQLite
  connections; reason: relational integrity should not depend on application
  discipline.
- Wrap multi-row writes in transactions; reason: plan changes, invites, and
  billing updates must not partially commit.
- Prefer explicit SQL query helpers over string-building in actions; reason:
  mutations are easier to review and test when SQL lives near the domain.
- Add an integration test for every migration that changes constraints or data
  shape; reason: SQLite accepts many shapes that only fail at runtime.

## Data Access Patterns

- Server components may call read-only query helpers directly.
- Server actions and route handlers are the only places that may perform writes.
- Every write path must call `requireUser()` or a more specific permission helper
  before touching the database.
- Validate untrusted input with Zod before constructing SQL parameters.
- Return small DTOs from query helpers instead of raw database rows; reason: UI
  components should not learn storage details.

## App Router Patterns

- Use `page.tsx` for route composition and load data there or in colocated
  server helpers.
- Use `loading.tsx`, `error.tsx`, and `not-found.tsx` for real route states, not
  ad hoc spinners embedded deep in business components.
- Use server actions for form submissions that mutate first-party data.
- Use route handlers for webhooks, third-party callbacks, public APIs, and
  streaming responses.
- Revalidate by path or tag after writes; reason: users should see the result of
  their action without a manual refresh.

## Component Patterns

- Components are server components unless they need browser state, effects, or
  event handlers.
- Client components receive serializable props only; reason: they cross the
  server/client boundary.
- Put form interactivity in a small client shell and keep validation/business
  logic in shared schemas and server actions.
- UI primitives in `components/ui/` must not import app-specific queries or
  actions; reason: reusable components should remain portable.
- Empty, loading, error, and permission-denied states are part of the component
  contract; reason: SaaS users spend real time in edge states.

## Auth, Tenancy, And Permissions

- All tenant-scoped queries must include `team_id` or the relevant ownership key.
- Do not trust IDs from forms or URLs until ownership is checked server-side.
- Keep role checks in `lib/permissions.ts`; reason: scattered role logic becomes
  inconsistent.
- For admin routes, check both authentication and role before loading privileged
  data.
- For webhooks, verify signatures before parsing business payloads.

## Billing And Entitlements

- Treat billing provider events as eventually consistent.
- Store provider event IDs and ignore duplicates.
- Separate plan state from usage counters; reason: plan changes and metered
  usage have different lifecycles.
- Check entitlements in the server action or route handler that performs the
  paid action, not only in the UI.

## Testing Expectations

- Unit test pure validators, formatting, and permission helpers.
- Integration test server actions with a temporary SQLite database.
- Test migrations against an empty database and at least one previous schema
  when practical.
- E2E test the money path: signup, create team, use the primary feature, change
  plan, and cancel.
- Add regression tests for every fixed bug before changing implementation.

## What We Do Not Do

- Do not put database calls in client components; reason: it leaks boundaries and
  cannot safely protect secrets.
- Do not bypass migrations with `CREATE TABLE IF NOT EXISTS` inside request
  handlers; reason: request traffic should not mutate schema.
- Do not add a generic repository layer unless it removes real duplication;
  reason: SQL is clearer than a thin abstraction that hides important joins.
- Do not use `any` to silence domain or billing types; reason: unclear money and
  permission types become production bugs.
- Do not trust optimistic UI as authorization; reason: users can call server
  actions directly.
- Do not add dependencies for one-line helpers; reason: SaaS apps already carry
  enough supply-chain surface.

## PR Checklist

- The change keeps server-only logic out of client bundles.
- SQL changes include a migration and a test.
- New env vars are documented in `.env.example`.
- Mutations validate input and check permissions server-side.
- Lint, typecheck, tests, and relevant E2E flows pass.
- The main user-facing states are covered: loading, empty, error, success, and
  permission denied.
