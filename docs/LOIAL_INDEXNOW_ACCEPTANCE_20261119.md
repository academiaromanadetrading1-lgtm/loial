# LOIAL — production discovery acceptance, 2026-11-19

- Production deployment `1bdeabfe-dc4b-473f-8b66-f3d19137feeb`: SUCCESS; source `aa2aa9e3943839abaa499621d8a9e729899473bf`.
- Persistent `/data` volume retained. No billing activation or database configuration changes.
- Regression run `44522069093`: 231 isolated tests + 1 full integration test passed; staging HTTP checks passed for root, sitemap, robots, llms, product overview, comparison, root verification key and wrong-key rejection.
- Owner executed `loial_indexnow.py --initial --submit` in production console; supplied screenshot shows `IndexNow accepted 29 URLs: HTTP 202; indexing not guaranteed`.
- Google and Bing sitemap submissions confirmed by owner screenshots. Actual indexing and AI visibility remain unverified.
- Future changed URL notifications: run `loial_indexnow.py --url https://loial.space/PUBLIC-PATH --submit` after successful release; explicit manual invocation, not an automatic scheduler. Avoid repeated identical submissions.

## Release boundaries
Public website and free pilot are online. Physical phone/camera/printer end-to-end validation and real merchant onboarding remain operational gates. Paid billing remains intentionally disabled. Do not claim full commercial readiness or search rankings before evidence.
