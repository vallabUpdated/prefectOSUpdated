# Expected findings

What `loan_extractors.py` reports for each bundle. `verify_kit.py` asserts all
of it (134 checks); if the two disagree, one of them is wrong and the demo is
not safe to run.

Figures are as printed by the engine. Every criterion is `met`, `not_met` or
`unverified` — an absent document is never silently treated as satisfied.
Positive bundles are clean on all seven criteria; negative bundles fail on
different ones, so each product has a distinct story.

| Bundle | Documents | Exceptions | Criteria not met |
|---|---|---|---|
| `home_loan_positive` | 4 clean | — | none |
| `home_loan_negative` | 4 exception | 6 | 5 of 7 |
| `mortgage_loan_positive` | 4 clean | — | none |
| `mortgage_loan_negative` | 3 clean, 1 exception | 1 | 2 of 7 |
| `personal_loan_positive` | 3 clean | — | none |
| `personal_loan_negative` | 3 clean | — | 1 of 7 (FOIR) |
| `vehicle_loan_positive` | 3 clean | — | none |
| `vehicle_loan_negative` | 2 clean, 2 exception | 3 | 2 of 7 |

## home_loan_positive — Priya Raghavan, HL-2026-004471

4 documents, all `clean`, no exceptions. Seven criteria, all `met`:

| Criterion | Evidence |
|---|---|
| FOIR at or below 50% | EMI 39,766.98 / net pay 108,450.00 = 36.67% |
| EMI consistent across documents | sanction letter 39,766.98 vs EMI schedule 39,766.98 |
| Borrower name consistent | Priya Raghavan in all four |
| Loan account number consistent | HL-2026-004471 in three |
| EMI schedule reconciles | 12 rows recomputed; every total matches |
| Loan statement reconciles | 12 rows recomputed; every total matches |
| Salary slip arithmetic | gross 128,000.00, net 108,450.00 |

Documents reconciled in code: 4 of 4. AI share 0%.

## home_loan_negative — Arjun Mehta, HL-2026-004902

4 documents, all `exception`. One seeded defect per document:

| Document | Reason | Stated | Recomputed |
|---|---|---|---|
| `01_sanction_letter.pdf` | `emi_mismatch` | 30,822.37 | 33,222.37 |
| `02_salary_slip.pdf` | `net_pay_mismatch` | 58,500.00 | 53,500.00 |
| `03_emi_schedule.pdf` | `balance_chain_break` (row 7) | 3,123,550.80 | 3,141,550.80 |
| `03_emi_schedule.pdf` | `interest_mismatch` (row 8) | 24,608.81 | 24,467.81 |
| `03_emi_schedule.pdf` | `balance_chain_break` (row 8) | 3,132,937.24 | 3,114,937.24 |
| `04_loan_account_statement.pdf` | `statement_total_closing_mismatch` | 3,137,597.41 | 3,150,097.41 |

Row 8 appears because the chain re-joins the true figures there: one altered
closing balance breaks the row it sits on and the row after it, and nothing
else. Rows 1-6 and 9-12 pass.

Cross-document verdicts — five `not_met`, two `met`:

| Criterion | Status | Evidence |
|---|---|---|
| FOIR at or below 50% | not_met | EMI 30,822.37 / net pay 58,500.00 = 52.69% |
| EMI consistent across documents | not_met | sanction letter 30,822.37 vs EMI schedule 33,222.37 |
| Borrower name consistent | met | Arjun Mehta in all four |
| Loan account number consistent | met | HL-2026-004902 in three |
| EMI schedule reconciles | not_met | rows 7 and 8 |
| Loan statement reconciles | not_met | closing balance out by 12,500.00 |
| Salary slip arithmetic | not_met | gross 60,000.00, net 58,500.00 |

The FOIR figure uses the payslip's *inflated* net pay, which is the honest way
to read it: even taking the document at its word, the file fails.

## mortgage_loan_positive — Devendra Iyer, LAP-2026-007713

4 documents, all `clean`. FOIR 41.13% (EMI 82,250.43 / net 200,000.00). All
seven criteria `met`.

## mortgage_loan_negative — Meera Sundaram, LAP-2026-008145

4 documents. Three are `clean`; only the schedule is an `exception`. Nothing
here is an arithmetic error inside a row — the file simply does not describe one
consistent application.

| Document | Reason | Stated | Recomputed |
|---|---|---|---|
| `03_emi_schedule.pdf` | `schedule_total_interest_mismatch` | 581,739.98 | 577,739.98 |

The twelve schedule rows all recompute correctly; it is the totals line beneath
them that overstates interest by 4,000.00.

| Criterion | Status | Evidence |
|---|---|---|
| FOIR at or below 50% | met | EMI 75,877.51 / net pay 173,000.00 = 43.86% |
| EMI consistent across documents | met | sanction letter and schedule agree at 75,877.51 |
| Borrower name consistent | **not_met** | sanction letter, payslip and schedule say Meera Sundaram; the statement says Meera R Sundaram |
| Loan account number consistent | met | LAP-2026-008145 in three |
| EMI schedule reconciles | **not_met** | stated 581,739.98 vs recomputed 577,739.98 |
| Loan statement reconciles | met | 8 rows recomputed; every total matches |
| Salary slip arithmetic | met | gross 202,000.00, net 173,000.00 |

## personal_loan_positive — Tara Venkatesh, PL-2026-551997

3 documents (no statement), all `clean`. FOIR 28.66% (EMI 16,622.51 / net
58,000.00) — inside the 40% personal-loan threshold in the box's default prompt
as well as the 50% coded check. Six criteria `met`; "Loan statement reconciles"
is `unverified`, because there is no statement in the folder.

## personal_loan_negative — Rehan Qureshi, PL-2026-553104

3 documents, all `clean`, no exceptions. FOIR **not_met** at 53.78% (EMI
25,276.37 / net 47,000.00). Every other criterion `met`, except the absent
statement, which is `unverified`. The file is arithmetically perfect and still
declines — that separation is the point of the bundle.

## vehicle_loan_positive — Sneha Kulkarni, VL-2026-118820

3 documents (no statement), all `clean`. FOIR 28.61% (EMI 24,349.31 / net
85,100.00). Six criteria `met`, statement `unverified`.

## vehicle_loan_negative — Karan Bhatia, VL-2026-119045

4 documents. The sanction letter and the EMI schedule are `clean`; the payslip
and the loan statement are not. Both defects sit inside a document's own
arithmetic — nothing was tampered across documents, and nothing breaches policy.

| Document | Reason | Stated | Recomputed |
|---|---|---|---|
| `02_salary_slip.pdf` | `deductions_mismatch` | 9,000.00 | 11,000.00 |
| `04_loan_account_statement.pdf` | `balance_chain_break` (`TXN0005`, 2026-10-12) | 1,416,281.88 | 1,425,781.88 |
| `04_loan_account_statement.pdf` | `balance_chain_break` (`TXN0006`, 2026-10-16) | 1,394,435.85 | 1,384,935.85 |

Provident fund 4,800.00 plus tax 6,200.00 is 11,000.00, and the slip prints
9,000.00 — which flatters net pay by the same 2,000.00. Gross still equals its
components and net pay still equals gross minus the *stated* deductions, so the
deductions line is the only thing wrong on the slip. In the statement, one
altered running balance breaks its own row and the row after it, where the
ledger re-joins the true figures; the stated totals still tie.

| Criterion | Status | Evidence |
|---|---|---|
| FOIR at or below 50% | met | EMI 31,346.03 / net pay 71,000.00 = 44.15% |
| EMI consistent across documents | met | sanction letter and schedule agree at 31,346.03 |
| Borrower name consistent | met | Karan Bhatia in all four |
| Loan account number consistent | met | VL-2026-119045 in three |
| EMI schedule reconciles | met | 12 rows recomputed; every total matches |
| Loan statement reconciles | **not_met** | `TXN0005` and `TXN0006` |
| Salary slip arithmetic | **not_met** | gross 80,000.00, net 71,000.00 |

## Application-stage bundles

Generated by `application_docs.py`; verified by `verify_kit.py` (slip parses, templates classify,
set complete, no stray type markers) and run through the engine when built. The decision is
the model's, so it can vary in wording; the criteria below are what the documents establish.

### home_loan_application_positive — Rahul Sharma

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar.pdf, 03_income_proof_salary_form16.pdf, 04_property_sale_deed_ec_valuation.pdf, 05_bank_statements_6_months.pdf, 06_credit_report.pdf

**Expected decision: ELIGIBLE**

- age 38, 58 at maturity; 6 months of stable salary credits matching slips
- FOIR 36.7% (EMI 52,069.39 / net 142,000.00)
- LTV 70.6%
- credit score 782, no write-offs
- clear EC, approved building plan + OC, valuation annexed
- KYC complete

### home_loan_application_negative — Deepak Rao

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar.pdf, 03_income_proof_salary_form16.pdf, 04_property_sale_deed_ec_valuation.pdf, 05_bank_statements_6_months.pdf, 06_credit_report.pdf

**Expected decision: NOT_ELIGIBLE**

- FOIR 121.8% (EMI 69,425.86 / net 57,000.00) - above 50%
- LTV 95.2% - above 80%
- credit score 641 with a write-off (03-2025) and a settlement (08-2025)
- EC shows an undischarged mortgage and pending litigation; no approved building plan
- March salary slip tampered: Gross Earnings 92,000.00 vs components 65,000.00 (extractor flags gross_mismatch)

### vehicle_loan_application_positive — Priya Menon

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar_licence.pdf, 03_income_proof_salary_form16.pdf, 04_vehicle_proforma_invoice.pdf, 05_bank_statements_6_months.pdf, 06_credit_report.pdf

**Expected decision: ELIGIBLE**

- age 33; licence valid till 2035
- EMI-to-income 20.2% (EMI 25,202.23 / net 125,000.00)
- LTV 78.9% of ex-showroom
- credit score 760, no vehicle-loan default
- proforma invoice, insurance and registration in the applicant's name
- KYC complete

### vehicle_loan_application_negative — Arjun Iyer

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar_licence.pdf, 03_income_proof_salary_form16.pdf, 04_vehicle_proforma_invoice.pdf, 05_bank_statements_6_months.pdf, 06_credit_report.pdf

**Expected decision: NOT_ELIGIBLE**

- driving licence EXPIRED 02-02-2026
- EMI-to-income 144.4% - above 45%
- LTV 98.7% - above 85%
- credit score 612 with a two-wheeler loan default / repossession
- only 1 year in current job; net income below a typical floor for this ticket size

### personal_loan_application_positive — Sneha Kulkarni

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar.pdf, 03_income_proof_salary_form16.pdf, 04_bank_statements_6_months.pdf, 05_credit_report.pdf

**Expected decision: ELIGIBLE**

- age 34; salaried 6 years
- EMI-to-income 14.4% (EMI 16,846.98 / net 117,000.00)
- credit score 745, no delinquency in 12 months
- salary credits 117,000.00 in the bank statement match the slips
- 1 active unsecured loan
- KYC complete

### personal_loan_application_negative — Vikram Nair

Documents: 01_loan_application_form.pdf, 02_identity_proof_pan_aadhaar.pdf, 03_income_proof_salary_form16.pdf, 04_bank_statements_6_months.pdf, 05_credit_report.pdf

**Expected decision: NOT_ELIGIBLE**

- EMI-to-income 97.8% including existing EMIs - above 40%
- credit score 688 with a 45-day delinquency in 05-2026
- 4 active unsecured loans (limit 3)
- bank statement salary credits 48,200.00 do NOT match the slips' net pay 57,500.00

## home_loan_two_applicants

`home_loan_positive` and `home_loan_negative` in one folder, 8 documents. Two
applicants detected:

- `HL-2026-004471` — Priya Raghavan, 4 documents, all seven criteria met
- `HL-2026-004902` — Arjun Mehta, 4 documents, five criteria not met

14 criteria in total, each labelled with the applicant. Every `not_met` belongs
to Arjun Mehta. Documents reconciled in code: 4 of 8 — AI share 50%.

## account_statement_csv

`current_account_jun_jul_2026.csv`, parsed as `csv_statement`, status `clean`,
no exceptions.

| Field | Value |
|---|---|
| Transactions | 24 |
| Period | 2026-06-01 to 2026-07-31 |
| Sign convention | `deposit` (inferred, not assumed) |
| Opening balance (implied) | 1,284,500.00 |
| Closing balance | 1,634,420.00 |
| Total debits / count | 2,180,150.00 / 14 |
| Total credits / count | 2,530,070.00 / 10 |
| Average balance | 1,612,469.67 (daily closing, days without a transaction carried forward) |
| Cheques returned | 2 |

The returned cheques: `CHQ100232` on 2026-06-10 for 141,000.00 (insufficient
funds) and `CHQ100235` on 2026-07-17 for 64,800.00 (drawer signature differs).
The two transfers to and from Halcyon Exports reverse within two days — the
model is expected to raise them; nothing in code does.

Columns are matched by synonym from `Date`, `Chq/Ref No`, `Narration`,
`Withdrawal Amt`, `Deposit Amt`, `Closing Balance`.

## kyc_set

4 text documents, no deterministic parser, so all four go to the model in full.
Nothing here is asserted by `verify_kit.py` beyond discoverability — the
findings are the model's. What is planted for it to find:

- `tax_identifier.txt` names "Arjun Mehtaa" (spelling) with date of birth
  1989-04-21, against "Arjun Mehta" and 1989-04-12 on `identity_card.txt`;
- `expired_employment_letter.txt` expired on 2026-02-28;
- address proof and identity document otherwise agree.

Expect KYC INCOMPLETE or NEEDS REVIEW, with the name and date-of-birth
mismatches and the expired letter listed.

## bundles_excel — the Excel twins

`bundles_excel/` holds the same 12 bundles as `.xlsx`, one file per native
document, carrying the same figures and the same seeded defects.

There is no Excel parser in `loan_extractors.py`, so every `.xlsx` comes back:

| Field | Value |
|---|---|
| status | `unreadable` |
| exception | `could_not_open` — "Is this really a PDF?" |
| routed to | the model, as text extracted by `loan_processing.extract_text` |

`unreadable` is not a failure verdict here: it is what tells the deterministic
run to put the document's full text in front of the model rather than an error
message. So an Excel bundle processes end to end, at 100% AI share and full
token cost, and the findings are the model's rather than recomputed arithmetic.

`verify_kit.py` asserts the mirror is complete (same bundles, one `.xlsx` per
document) and that the figures survive the format: the tampered row 7 balance
`3,123,550.80`, the amortised EMI `33,222.37` and the understated sanction EMI
`30,822.37` all appear in the text the model receives. The pandas/openpyxl
checks are skipped with a note if those packages are missing.

## general_mixed

3 documents — the account CSV, a sanction letter and a covering note — for the
ad-hoc box. No fixed expectation: the prompt is meant to be rewritten live.
