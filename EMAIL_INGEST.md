# Email Intake — Ops Guide

Clients email PDF document packs to a dedicated mailbox; the connector
validates them in three stages, parks accepted packs for human review,
and the reviewer processes them into the right queue from the UI.

## Validation stages
1. **Sender** — allowlist route (→ client + product), address syntax,
   SPF/DKIM/DMARC from Authentication-Results (anti-spoofing).
2. **Templates** — PDF structure + classification against
   doc_templates.json (pdfplumber → pypdf → built-in fallback).
3. **Document set** — the pack must be complete for the product
   (e.g. home_loan: application_form + identity_proof + income_proof +
   property_document); rejects name the exact missing types.

## Review flow
Validated packs appear under **Email Intake** in the Processing sidebar
(badge + banner). The reviewer reads the email body, downloads any
document, then **Process documents →** submits to the queue resolved
from the product (`user_id = client::queue`), or **Discard** with a
reason. Both are idempotent and sealed with the approver's identity.

## Configuration (Settings ⚙)
* **Email intake** — mailbox status, SPF/DKIM toggle, sender routes.
* **Document templates** — keywords/pages per doc type (Loans / KYC /
  Accounts) and required sets per product.
Saves write email_ingest_config.json / doc_templates.json and seal
`routes_updated` / `template_updated` (content SHA-256, approver) into
the hash-chained email audit log. Verify any time:
`python email_ingest.py --verify-audit`.

## Setup
1. Dedicated mailbox, IMAP enabled, app password created. Plus-
   addressing (docs+homeloan@…) works out of the box on Gmail.
2. `/etc/prefectos/env` (chmod 600): `EMAIL_INGEST_PASSWORD=…`
   — the password is NEVER in config or code.
3. Rehearse: `python email_ingest.py --dry-run --once`
4. Run: `python email_ingest.py --poll 120`, or install the unit below.

## systemd — /etc/systemd/system/prefectos-email.service
```ini
[Unit]
Description=PrefectOS email ingestion connector
After=network-online.target prefectos.service

[Service]
User=vallab
WorkingDirectory=/home/vallab/prefectOSUpdated/repo
EnvironmentFile=/etc/prefectos/env
ExecStart=/usr/bin/python3 email_ingest.py --poll 120
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now prefectos-email` ·
logs: `journalctl -u prefectos-email -f`

## Failure semantics
* Queue/API down → `process_failed` ledgered; intake stays pending for
  another click. Connector-side submit failures leave mail unseen for
  retry. Nothing lost, nothing double-processed.
* Unknown/spoofed sender → rejected; attachments never touch disk.
* Resent documents → SHA-256 duplicate; can't complete a new pack.
* Scanned image-only PDFs extract no text → `no_extractable_text`;
  route them through OCR before classification, or relax per client.

## Tests
`python -m pytest tests/test_email_ingest.py -q` — 23 offline tests.
