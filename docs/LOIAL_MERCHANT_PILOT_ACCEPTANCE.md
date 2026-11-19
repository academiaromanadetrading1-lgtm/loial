# LOIAL — merchant pilot acceptance

Status: planned, not executed. Free pilot only; no live billing.

## Preconditions
- Use consented test participants and a designated merchant account; never reuse superadmin credentials.
- Record test device, OS/browser, printer model, POS software and integration method. Never include customer secrets or personal identifiers in screenshots.
- Prefer staging for synthetic transactions. Production checks must use a designated pilot merchant and clearly identified test transactions.
- Confirm a recent verified production SQLite backup before any production write test.

## Physical acceptance matrix

| ID | Procedure | Expected | Evidence |
|---|---|---|---|
| P01 | Print itemized prepayment ticket with unique LOIAL QR from supported POS integration | QR legible; amounts and items match order | Redacted ticket |
| P02 | Scan printed code with native Android camera | Correct HTTPS merchant/order page | Device/browser and screenshot |
| P03 | Repeat on native iOS camera | Same result | Device/browser and screenshot |
| P04 | Customer reserves ticket and displays customer QR | Correct pending order; no premature award | Redacted screenshot |
| P05 | Staff confirms payment using customer QR | Correct award and itemized history | Before/after balance |
| P06 | Scan again or reprint same ticket | No duplicate award | Before/after balance |
| P07 | Concurrent attempts from two devices | Single successful award | Redacted transaction outcome |
| P08 | Unpaid/cancelled order | No award | Staff outcome |
| P09 | Different merchant attempts to redeem | Rejected, no balance change | Response |
| P10 | Interrupt network during confirmation; retry after reconnection | No duplicate award; clear status | Device outcome |
| P11 | Add LOIAL wallet to home screen on Android and iOS | Opens relevant wallet; no Apple/Google Wallet dependency | Screenshots |
| P12 | Send permitted merchant campaign; customer opts out | No subsequent promotional delivery after opt-out | Redacted inbox |
| P13 | Merchant A tries to view Merchant B customer/order records | Access rejected | Response |
| P14 | Sign out from customer, merchant and ambassador | Returns to public homepage | Screen recordings |
| P15 | Real pilot merchant independently completes onboarding | Can operate supported flow with documented assistance only | Written consented feedback |

## Launch gate
Critical P01–P10 and P13 must pass for the particular supported POS/printer configuration before promoting that configuration. Do not claim compatibility with untested POS hardware. Android/iOS tests must use physical devices; browser emulation is not equivalent. Record pass/fail/blocked separately, never mark a test passed without evidence.

## Pilot expansion
Begin with one merchant and controlled transactions; expand to a small cohort only after acceptance. Log defects by severity; any duplication, unauthorized access, inaccurate credit or cross-merchant data exposure stops expansion. No paid plan activation until explicitly approved and billing verified independently. No extra runner or infrastructure purchases assumed.
