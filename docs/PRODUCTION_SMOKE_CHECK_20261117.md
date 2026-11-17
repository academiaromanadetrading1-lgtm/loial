# Production smoke check — read-only
Run in Railway Console on the active service, using the installed Python. No credentials, external AI, customer records or mutations. Only GET requests; no signup or payment.

```bash
/app/.venv/bin/python - <<'PY'
import json, urllib.request, urllib.error
base = "http://127.0.0.1:8080"
checks = {"/health":200, "/":200, "/wallet":200, "/manifest.json":200, "/sw.js":200, "/pwa-icon-192.png":200, "/pwa-icon-512.png":200, "/demo":200, "/ambasadori":200, "/robots.txt":200, "/sitemap.xml":200, "/api/loial-plans":200, "/api/loial-plans/simulate?new_business=10&renewed_business=30&new_pro=5&renewed_pro=10&recruited_business=5":200, "/api/loial-identity/me":401, "/api/loial-stripe/me":401}
failed = 0
for path, expected in checks.items():
    try:
        with urllib.request.urlopen(base+path, timeout=10) as r:
            status=r.status
            if path=="/api/loial-plans":
                assert [(x["code"],x["price_eur"]) for x in json.load(r)]==[("start",0),("business",67),("probusiness",270)]
            if path.startswith("/api/loial-plans/simulate?"):
                data=json.load(r)
                assert data["total_commission_cents"]==170000 and data["scenario_only"] is True
    except urllib.error.HTTPError as e:
        status=e.code
    except Exception as e:
        status=type(e).__name__
    ok=status==expected
    failed+=not ok
    print("PASS" if ok else "FAIL",path,status)
print("TOTAL",len(checks)-failed,"/",len(checks))
raise SystemExit(bool(failed))
PY
```

This checks the local deployed app, not external DNS/TLS or real devices. Do not paste secrets. The existing live deployment does not include the pending favicon fix. Verify old OpenAI key revocation separately. No automatic production deployment authorized by this document.
