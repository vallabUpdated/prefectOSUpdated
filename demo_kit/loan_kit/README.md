# Sample loan processing kit

A set of synthetic loan, account and KYC documents for client demos, plus the
generator that produced them and a verifier that proves they still behave as
the demo script says. Every loan product ships a **positive** and a
**negative** bundle, so each one can be shown passing and failing, and
**+ Sample Preset** on any box lands on documents that exist.

Everything here is fabricated. Every page carries a SPECIMEN stamp, the banks,
employers and people are invented, and the identifiers use reserved or masked
formats. Nothing in the kit came from a customer.

## Before the demo

```bash
pip install pdfplumber                      # the deterministic PDF path needs it
pip install pandas openpyxl                 # only for the Excel bundles
python demo_kit/loan_kit/verify_kit.py      # 134 checks, ~5s — run this first
python server.py                            # then open the Processing page
```

`verify_kit.py` drives the real extractors (`loan_extractors.py`) over the kit
and asserts every finding listed in [EXPECTED.md](EXPECTED.md). If it exits 0,
the demo will say what this runbook says it will. If a change to the extractors
alters a verdict, it fails loudly here instead of in front of a client.

A live run still ends with one model call for the eligibility assessment, so
have `ANTHROPIC_API_KEY` set (or `DEFAULT_PROVIDER=ollama` with a local server)
before demoing.

## The bundles

| Folder | Box | Docs | Verdict | What it shows |
|---|---|---|---|---|
| `home_loan_positive` | Home | 4 | passes | Straight through: every figure reconciles, FOIR 36.67%, **0% of documents go to the model** |
| `home_loan_negative` | Home *(preset)* | 4 | fails | Four seeded defects, one per document — the tampered-file story |
| `mortgage_loan_positive` | Mortgage | 4 | passes | Clean LAP file, FOIR 41.13% |
| `mortgage_loan_negative` | Mortgage *(preset)* | 4 | fails | No figure is wrong on its own; the file still does not hang together |
| `personal_loan_positive` | Personal | 3 | passes | Clean unsecured file, FOIR 28.66% |
| `personal_loan_negative` | Personal *(preset)* | 3 | fails | Arithmetic perfect, **declined on policy**: FOIR 53.78% |
| `vehicle_loan_positive` | Vehicle | 3 | passes | Clean vehicle file, FOIR 28.61% |
| `vehicle_loan_negative` | Vehicle *(preset)* | 4 | fails | The servicing documents do not tie: a short deductions column and a running balance that jumps |
| `home_loan_two_applicants` | — | 8 | mixed | Both home-loan applicants in one folder, split by loan account number; **50% AI share** |
| `account_statement_csv` | Account Processing *(preset)* | 1 | — | Bank CSV export: columns matched by synonym, 24 transactions, 2 returned cheques, zero tokens |
| `kyc_set` | KYC *(preset)* | 4 | fails | Name and date of birth disagree across documents; the employment letter has expired |
| `general_mixed` | General *(preset)* | 3 | — | A CSV, a PDF and a covering note — the ad-hoc box |

### The same kit in Excel

`bundles_excel/` mirrors `bundles/` document for document — 45 `.xlsx` files
across the same 12 bundles, same names, same figures, same seeded defects. Use
them for the client who says "our documents come out of the core system as
spreadsheets": point any box at `./demo_kit/loan_kit/bundles_excel/<bundle>`
instead.

**Know what changes when you do.** `loan_extractors.py` reconciles PDFs and
CSVs in code; it has no Excel parser. An `.xlsx` is therefore read by
`loan_processing.extract_text` (pandas + openpyxl) and sent to the model in
full — so an Excel bundle shows the model-led path at 100% AI share, not the
zero-token reconciliation. The findings come back as the model's reading of the
document, not as recomputed arithmetic with a stated-vs-recomputed figure
beside it. Demo the PDF bundle when the point is "we recompute it in code";
demo the Excel one when the point is "we read whatever you send". Adding a
deterministic Excel parser would close that gap and is not in this kit.

Each product's **+ Sample Preset** points at its negative bundle — the run that
shows the engine catching something. Swap `_negative` for `_positive` in the
input path for the straight-through half.

A **Documents at this path** panel then lists what was found — name, type and
size — with **View** (opens the PDF or text in the browser) and **Download**
per document, and **⬇ Download all as .zip** for the whole bundle. Open the
sanction letter on screen and the client can read the EMI the engine is about
to contradict; the zip is what you send them afterwards. The panel follows the
input path, so it works for a client's own folder too, not just the kit.

The same click sets the output path to `demo_kit/loan_kit/output/<box>` and
creates the folder, so **📂 Browse…** opens it and the operator can see where
the reports will land before starting. Each run then writes its own
`<timestamp>_<type>/` folder there, holding `eligibility_report.json`, `.md`
and `.html`. Demo artifacts stay beside the documents that produced them and
are git-ignored; delete `demo_kit/loan_kit/output/` to reset between clients.

## A 17-minute demo

**1 — The straight-through case (3 min).**
Home Loan box, mode **⚡ Optimized AI**, input
`./demo_kit/loan_kit/bundles/home_loan_positive`. Every document comes back
clean, the AI share reads 0%, and the report shows seven criteria met with the
figures behind each one. The point to make: *nothing here was inferred — the EMI
was recomputed from principal, rate and tenure, and the schedule was re-added
row by row.*

**2 — The same file, tampered (4 min).**
Point the same box at `home_loan_negative` (or just click **+ Sample Preset**).
Four documents, four different failure classes, each with the stated figure and
the recomputed one side by side:

- the sanction letter's EMI does not follow from its own terms — 30,822.37
  stated against 33,222.37 amortised;
- the payslip's NET PAY is 5,000 above gross minus deductions;
- row 7 of the schedule has been altered, and the chain breaks at row 7 and
  again at row 8 where it re-joins the true figures — every other row passes;
- the statement's ledger ties, but its stated closing balance does not.

Then the cross-document verdicts: the EMI disagrees between the sanction letter
and the schedule, and FOIR fails at 52.69% *on the inflated payslip figure* —
on the arithmetic-correct net pay it is worse.

**3 — A mortgage that fails without a single wrong figure (3 min).**
Mortgage box, `mortgage_loan_positive` first: clean, FOIR 41.13%, seven criteria
met. Then `mortgage_loan_negative`. Every document is internally sound, and the
file still fails twice over: the EMI schedule's totals line overstates interest
by 4,000 against the rows printed directly above it, and the statement names
"Meera R Sundaram" where the rest of the file says "Meera Sundaram". This is the
answer to *"our problem isn't fraud, it's mismatched paperwork."*

**4 — Declined on policy, not on arithmetic (2 min).**
Personal Loan box, `personal_loan_positive` passes at FOIR 28.66%. Then
`personal_loan_negative`: every document is still clean, and the file fails
anyway, because the EMI takes 53.78% of take-home pay. Arithmetic and
eligibility are separate findings, and the report says which is which.

**5 — A vehicle loan whose servicing documents do not tie (2 min).**
Vehicle box, `vehicle_loan_positive` first: clean, FOIR 28.61%. Then
`vehicle_loan_negative`. The sanction letter and the twelve-row schedule are
both sound, and two documents still fail: the payslip's Total Deductions is
2,000 short of provident fund plus tax, and the loan account's running
balance jumps once — `TXN0005` states 1,416,281.88 where the row above it
leads to 1,425,781.88, and `TXN0006` breaks again where the ledger re-joins
the true figures. FOIR still passes at 44.15%: this file fails on
bookkeeping, not on affordability.

**6 — Two applicants in one folder (2 min).**
`home_loan_two_applicants`. The engine splits eight documents into two
applicants by loan account number, attaches each payslip to the right person,
and reports fourteen criteria — seven per applicant. Priya Raghavan passes,
Arjun Mehta fails. Half the documents needed the model; half were settled in
code. This is the slide about cost.

**7 — Whatever the bank actually exports (1.5 min).**
Account Processing box, **+ Sample Preset**. The CSV headers are
`Withdrawal Amt` / `Deposit Amt` / `Closing Balance` — not the canonical names —
and are matched by synonym. The debit/credit sign convention is inferred by
testing both against the balance chain. 24 transactions, both returned cheques
found with date, amount and stated reason, and the whole document costs nothing
to process.

Keep `kyc_set` and `general_mixed` in reserve for the "can it handle *our*
documents?" question: neither has a deterministic parser, so both demonstrate
the fallback — the document goes to the model in full rather than being
silently downgraded.

## Rebuilding

```bash
python demo_kit/loan_kit/build_kit.py     # regenerates every bundle
python demo_kit/loan_kit/verify_kit.py
```

`build_kit.py` computes the amortisation, the ledger chain and the payslip
arithmetic, then seeds defects by explicit deltas in `BUNDLE_SPECS`:

| Knob | Defect it produces |
|---|---|
| `emi_understated` | The sanction letter's EMI stops following from its own terms |
| `net_pay_overstated` | NET PAY no longer equals gross minus deductions |
| `tamper_row` / `tamper_amount` | One altered closing balance in the schedule |
| `schedule_totals_delta` | The schedule's totals line disagrees with its rows |
| `statement_closing_delta` | The statement's stated closing balance is wrong |
| `statement_break_index` / `statement_break_amount` | One running balance in the statement does not follow |
| `deductions_understated` | The payslip's Total Deductions is short of its own components |
| `statement_borrower` | The statement names a different borrower |

That is why a positive bundle is clean to the paisa and a negative one carries
exactly the listed defects and nothing else. To add a product, add an entry to
`BUNDLE_SPECS` and a case to `verify_kit.py`.

`minixlsx.py` writes the `.xlsx` twins from the same computed figures — a
zip of a few XML parts, inline strings and a money format, so the build needs
no spreadsheet library either. pandas and openpyxl are needed only to *read*
Excel, which is what the product does.

`minipdf.py` is a ~150-line PDF writer — positioned text, rules, shaded bands —
so the kit adds no dependency to the project. pdfplumber is needed only to
*read* the PDFs back, which is what the product does anyway.

## Editing the documents by hand

Don't. The parsers recompute what the documents state, so a hand-edited figure
becomes a defect the demo does not expect. Change `BUNDLE_SPECS` and rebuild.
If you do need a bespoke document, run `verify_kit.py` afterwards and update
EXPECTED.md to match what the engine actually reports.
