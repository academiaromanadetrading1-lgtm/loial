# LOIAL Print API

Each merchant generates a private integration key in its dashboard. Store it on the merchant's server or trusted connector, never in a public browser or on the printed receipt.

POST https://loial.space/api/loial-receipts/integration/issue
Header: X-Loial-Receipt-Key: <merchant key>
Content-Type: application/json

Example:
```json
{"receipt_ref":"LOCATION1-2026-000123","currency":"RON","expires_days":1,"lines":[{"product":"Cafea","quantity":2,"unit_price":12.5}]}
```

Print the PNG in qr_png_base64 or encode claim_url using the existing receipt template. Keep the same unique receipt_ref and identical payload on reprints. A changed payload under that reference is rejected. A claimed, refunded or expired note cannot be reissued under the same reference. Use genuinely unique references across locations and days.

The API always creates unpaid notes. No stamp or recognized sale is created until an authorized employee confirms after receiving payment. The API key cannot confirm payment, read CRM, or issue stamps. Rotate or revoke keys in the dashboard.

This is a generic HTTP interface, not a certified connector to any particular vendor. Printing software must support an HTTP integration or a vendor-specific adapter. Real printer tests and concurrent retry tests are required before rollout. Do not send payment card data.
