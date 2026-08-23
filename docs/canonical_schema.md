# PrefectOS canonical extraction schema (v1)

Every extractor — internal deterministic, external vendor adapter, or LLM-repaired —
translates INTO this shape. Downstream (worker terminal states, reports, ledger,
eligibility logic) consumes ONLY this schema and never knows who produced it.

| Field           | Type                | Semantics |
|-----------------|---------------------|-----------|
| doc_id          | str                 | Stable id (filename stem by default) |
| status          | str                 | "clean" \| "exception" \| "unreadable" |
| header          | dict                | account_no, ifsc, account_type, currency, period_from, period_to, opening_balance (float) — absent keys allowed |
| n_transactions  | int                 | len(transactions) |
| transactions    | list[dict]          | date (ISO str), txn_id, channel, narration, direction ("debit"\|"credit"), amount (float), balance (float) |
| totals          | dict                | stated: {debits, credits, closing_balance}, computed: {same keys} — floats; either side may be partial |
| exceptions      | list[dict]          | scope ("row"\|"totals"), txn_id?, reason, raw (source text) |
| elapsed_ms      | float               | Producer-side processing time |
| provenance      | dict (OPTIONAL, v1.1) | producer ("internal"\|vendor name), vendor_ref?, translated_at — added by external adapters |

Rules: amounts are floats rounded to 2dp; running balance must be recomputable
(balance[i] = balance[i-1] ± amount) for "clean"; any field an adapter cannot
supply is omitted, never invented.
