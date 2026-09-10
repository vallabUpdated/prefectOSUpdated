# Email Module — Files to Add / Modify

Extract this zip over your project root (prefectOSUpdated/). Paths are
preserved, so every file lands in the right place. All modified files
here are COMPLETE files (original content + the email changes applied),
based on your latest project zip — if you've edited any of them since,
apply the "what changed" notes manually instead of overwriting.

## ADDED — 11 files (safe to copy in, nothing to merge)

Backend (project root):
  email_ingest.py          IMAP connector: 3-stage validation, review-
                           mode parking, hash-chained audit, CLI
                           (--once/--poll/--dry-run/--verify-audit)
  email_validation.py      sender authenticity (syntax + SPF/DKIM/DMARC),
                           template classification, doc-set completeness
  email_review.py          pending store + /email/* API: intake list,
                           detail (email body), document download,
                           process-to-queue, discard, and the settings
                           endpoints (/email/settings, /email/templates)
  doc_templates.json       templates for Loans / KYC / Accounts doc
                           types + required document_sets per product
  email_ingest_config.json mailbox, sender routes (senders → client →
                           product), flags, queue map — NO passwords
  EMAIL_INGEST.md          ops guide + systemd unit
  tests/test_email_ingest.py   23 offline tests

Frontend (ui/src):
  components/EmailIntake.jsx        review screen (body, downloads,
                                    Process documents →, Discard)
  components/SettingsEmail.jsx      valid inboxes + sender routes pane
  components/SettingsTemplates.jsx  template + document-set editor pane
  styles_email.css                  styles for all three

## MODIFIED — 8 files (full replacements included here)

  batch_api.py
      after app.include_router(router):
      + from email_review import router as email_router
      + app.include_router(email_router)

  ui/src/components/ProcessingWindow.jsx
      + import EmailIntake
      + EMAIL rail entry const; saved-section check accepts "email"
      + pendingEmails state: polls /email/intake every 20s; listens for
        the "prefectos:email-intake" window event (LoanCard jump)
      + "Email Intake" button in the suites rail (live pending badge)
      + amber review banner at the top of <main> when pending > 0
      + render branch: section === "email" → <EmailIntake/>

  ui/src/components/LoanCard.jsx
      + emailPacks state (pending intakes for this product)
      + "✉ N validated packs arrived by email … Review & process →"
        hint above the scan hint; dispatches the jump event

  ui/src/components/SettingsDialog.jsx
      + imports SettingsEmail, SettingsTemplates
      + mounts both panes just before <footer className="st-foot">

  ui/src/styles_processing.css
      + .pw-email-banner rules (appended at end)

  requirements.txt         + pdfplumber
  .gitignore               + project_output/email_ingest/   (client PII)
  scripts/deploy.sh        + UI npm build + prefectos-email restart
                             (appended at end)

## After merging
  python -m pytest tests/test_email_ingest.py -q     # 23 passed
  cd ui && npm ci && npm run build
Server (once): EMAIL_INGEST_PASSWORD in /etc/prefectos/env, install the
prefectos-email systemd unit (see EMAIL_INGEST.md), first run with
  python email_ingest.py --dry-run --once
