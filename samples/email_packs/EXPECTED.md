# Expected outcomes for the email-intake sample packs

Send every PDF of a pack in ONE email to the mailbox shown, with the suggested subject
(the product is read from the subject). Each pack is a different fictional applicant.

## home_loan_positive - Rahul Sharma
Send to **loandocs@prefectos.ai**, subject `Home Loan application - Rahul Sharma`

**Expected decision: ELIGIBLE**
- age 38, 58 at maturity; 6 months of stable salary credits matching slips
- FOIR 36.7% (EMI 52,069.39 / net 142,000.00)
- LTV 70.6%
- credit score 782, no write-offs
- clear EC, approved building plan + OC, valuation annexed
- KYC complete

## home_loan_negative - Deepak Rao
Send to **loandocs@prefectos.ai**, subject `Home Loan application - Deepak Rao`

**Expected decision: NOT_ELIGIBLE**
- FOIR 121.8% (EMI 69,425.86 / net 57,000.00) - above 50%
- LTV 95.2% - above 80%
- credit score 641 with a write-off (03-2025) and a settlement (08-2025)
- EC shows an undischarged mortgage and pending litigation; no approved building plan
- March salary slip tampered: Gross Earnings 92,000.00 vs components 65,000.00 (extractor flags gross_mismatch)

## vehicle_loan_positive - Priya Menon
Send to **loandocs@prefectos.ai**, subject `Vehicle Loan application - Priya Menon`

**Expected decision: ELIGIBLE**
- age 33; licence valid till 2035
- EMI-to-income 20.2% (EMI 25,202.23 / net 125,000.00)
- LTV 78.9% of ex-showroom
- credit score 760, no vehicle-loan default
- proforma invoice, insurance and registration in the applicant's name
- KYC complete

## vehicle_loan_negative - Arjun Iyer
Send to **loandocs@prefectos.ai**, subject `Vehicle Loan application - Arjun Iyer`

**Expected decision: NOT_ELIGIBLE**
- driving licence EXPIRED 02-02-2026
- EMI-to-income 144.4% - above 45%
- LTV 98.7% - above 85%
- credit score 612 with a two-wheeler loan default / repossession
- only 1 year in current job; net income below a typical floor for this ticket size

## personal_loan_positive - Sneha Kulkarni
Send to **loandocs@prefectos.ai**, subject `Personal Loan application - Sneha Kulkarni`

**Expected decision: ELIGIBLE**
- age 34; salaried 6 years
- EMI-to-income 14.4% (EMI 16,846.98 / net 117,000.00)
- credit score 745, no delinquency in 12 months
- salary credits 117,000.00 in the bank statement match the slips
- 1 active unsecured loan
- KYC complete

## personal_loan_negative - Vikram Nair
Send to **loandocs@prefectos.ai**, subject `Personal Loan application - Vikram Nair`

**Expected decision: NOT_ELIGIBLE**
- EMI-to-income 97.8% including existing EMIs - above 40%
- credit score 688 with a 45-day delinquency in 05-2026
- 4 active unsecured loans (limit 3)
- bank statement salary credits 48,200.00 do NOT match the slips' net pay 57,500.00
