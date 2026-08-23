# Home Loan — eligibility report

- **Job**: `loan-home-79bcbc00`
- **Input**: `C:\Users\Suthej\Downloads\prefectos_v8_3_anthropic_keys\lc_lg_orchestrator_v2_Version6\tests\.e2e_tmp\docs`
- **Documents**: 4 processed
- **Tokens**: 8,346 in / 2,408 out
- **Cost**: $0.020 at list price (claude-haiku-4-5)
- **Time**: 32s
- **Mode**: deterministic — 0 reconciled in code, 4 escalated to AI (100% AI share)
- **Generated**: 2026-08-23T01:43:32.437027

## Decision: NEEDS_REVIEW

**Applicant**: unknown  
**Confidence**: low

This application cannot proceed to eligibility determination. All four documents in the applicant's file failed to open due to PDF parsing errors, leaving every criterion unverified. The applicant's name, identity, income, employment status, and any existing loan obligations remain entirely unknown. Without readable income proof (salary slip, employment letter, bank statement) and loan documents (sanction letter, loan statement), FOIR cannot be calculated, income consistency cannot be assessed, and borrower identity cannot be confirmed across documents. The file also lacks critical collateral and liability documentation. The decision is NEEDS_REVIEW pending resubmission of valid, readable documents.

## Criteria

| Check | Status | Evidence |
|---|---|---|
| FOIR (EMI to net monthly income ratio) at or below 50% | unverified | No loan statement or salary slip data available; documents could not be parsed |
| Borrower name consistent across all documents | unverified | All four documents failed to open; no names extracted from any document |
| Loan account number consistent across all documents | unverified | All four documents failed to open; no account numbers extracted |
| EMI stated in at least two independent documents and reconciled | unverified | All four documents failed to open; no EMI figures extracted from any source |
| EMI schedule totals arithmetically reconcile to stated values | unverified | No loan statement or schedule document available for review |
| Loan statement totals arithmetically reconcile to stated values | unverified | No loan statement document available in file |
| Salary slip gross, deductions, and net pay arithmetically consistent | unverified | payslip_march.txt failed to parse; no salary figures or deductions extracted |

## Missing documents

- bank_statement.txt (file corrupted or invalid PDF format)
- employment_letter.txt (file corrupted or invalid PDF format)
- id_card.txt (file corrupted or invalid PDF format)
- payslip_march.txt (file corrupted or invalid PDF format)
- Loan sanction letter or loan statement (required to verify FOIR and EMI)
- Property documents or title deed (standard collateral verification for home loan)
- Additional salary slips (minimum 2–3 months to establish income stability)
- Proof of other existing liabilities (required for complete FOIR calculation)

## Risk flags

- All four submitted documents are corrupted, malformed, or in unsupported file formats—none could be opened or parsed
- Applicant identity cannot be verified from any document
- No income or employment data is available
- No EMI or loan obligation data is available
- Critical file integrity issues suggest possible transmission failure, storage corruption, or invalid file uploads

## Next steps

- Contact the applicant to resubmit all four documents (bank statement, employment letter, ID, salary slip) in valid PDF or image format
- Verify that files have not been corrupted during transmission or upload; request fresh scans or exports
- Confirm expected file formats with the applicant (PDF, JPEG, PNG); reject any files with headers or corruption
- Once readable documents are received, re-run the processing pipeline against the plan
- Request loan sanction letter or loan statement to establish EMI and calculate FOIR
- Request property documents and full liability disclosure for complete risk assessment
- Request at least 2–3 recent consecutive salary slips to verify income stability

---

Home Loan eligibility report, generated 2026-08-23T01:43:32.437027. For internal credit review only.
Written to `C:\Users\Suthej\Downloads\prefectos_v8_3_anthropic_keys\lc_lg_orchestrator_v2_Version6\tests\.e2e_tmp\out\20260823_014300_home`.
