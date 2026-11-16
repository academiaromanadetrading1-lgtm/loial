"""Serviciu optional de email Loial. Dezactivat implicit; necesita chei noi, verificate."""
import base64
import hashlib
import hmac
import os
from urllib.parse import quote

import httpx

def email_enabled():
    return (os.getenv("LOIAL_EMAIL_ENABLED") == "1" and
            bool(os.getenv("LOIAL_SENDGRID_API_KEY")) and
            bool(os.getenv("LOIAL_EMAIL_FROM")) and
            os.getenv("LOIAL_PUBLIC_BASE_URL", "").startswith("https://"))

def unsubscribe_token(business_id, customer_id, secret):
    content = (str(business_id) + ":" + str(customer_id)).encode("utf-8")
    body = base64.urlsafe_b64encode(content).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig

def parse_unsubscribe_token(value, secret):
    if "." not in value or len(value) > 200:
        return None
    body, sig = value.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
        biz, client = raw.split(":")
        if not biz.isdigit() or not client.isdigit():
            return None
        return int(biz), int(client)
    except (ValueError, UnicodeError):
        return None

async def send_text_email(address, subject, body, unsubscribe_link):
    if not email_enabled():
        raise RuntimeError("Serviciul de email nu este configurat")
    # SendGrid v3 Mail Send. Text simplu, fara markup si fara atasamente.
    payload = {
        "personalizations": [{"to": [{"email": address}]}],
        "from": {"email": os.environ["LOIAL_EMAIL_FROM"]},
        "subject": subject[:180],
        "content": [{"type": "text/plain", "value": body[:5000] +
                       "\n\nNu mai doresti mesaje comerciale? " + unsubscribe_link}],
    }
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.post("https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": "Bearer " + os.environ["LOIAL_SENDGRID_API_KEY"],
                     "Content-Type": "application/json"},
            json=payload)
    return response.status_code == 202

def unsubscribe_url(business_id, customer_id, secret):
    token = unsubscribe_token(business_id, customer_id, secret)
    return os.environ["LOIAL_PUBLIC_BASE_URL"].rstrip("/") + "/unsubscribe.html?token=" + quote(token)
