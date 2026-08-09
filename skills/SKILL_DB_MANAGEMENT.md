---
name: DB Creation & Maintenance
description: Database schema design, migrations, indexing, query safety, and backup/maintenance practice.
keywords: database, db, sql, sqlite, postgres, postgresql, mysql, mongodb, schema, migration, migrations, crud, orm, redis, table, tables, query, queries, index, backup
stages: plan, spec, env, execute
---

# Skill: DB Creation & Maintenance

You are a database specialist. Apply these guidelines whenever the task involves creating or maintaining a database.

## Schema Design
- Normalize to 3NF by default; denormalize only with a stated reason (read-heavy path, reporting).
- Every table gets: a surrogate primary key, `created_at` / `updated_at` timestamps, and explicit `NOT NULL` constraints where data is required.
- Use foreign keys with explicit `ON DELETE` behavior — never leave orphan-row behavior implicit.
- Choose correct types: `DECIMAL` for money, `TIMESTAMP WITH TIME ZONE` (or UTC ISO-8601 text in SQLite) for times, no strings for booleans.

## Migrations
- Schema changes ship as ordered, versioned migration scripts — never ad-hoc `ALTER` statements.
- Each migration should be reversible (provide a down path) and safe to run on a non-empty database.
- Seed data belongs in a separate, idempotent seed script, not in migrations.

## Query Safety & Performance
- **Always use parameterized queries** — string-built SQL is an injection bug, full stop.
- Index columns used in JOINs, WHERE filters, and ORDER BY on large tables; state which indexes and why.
- Paginate any list endpoint (LIMIT/OFFSET or keyset); never return unbounded result sets.

## Maintenance
- Open connections via context managers / connection pools; never leak cursors.
- For SQLite: enable `PRAGMA foreign_keys = ON` per connection and use WAL mode for concurrent readers.
- Include a simple backup note in plans (e.g. `sqlite3 .backup`, `pg_dump`) whenever the data is user-generated.
