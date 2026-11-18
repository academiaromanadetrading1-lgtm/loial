from datetime import datetime, timezone
from collections import Counter
from types import SimpleNamespace as S
from loial_crm import metrics

def test_unknown_spend():
    now=datetime(2026,11,18,tzinfo=timezone.utc)
    result=metrics([], [S(source="manual",created_at=now.isoformat())], Counter(), now)
    assert result["verified_spend_minor"] is None
    assert result["loyalty_events"]==1
    assert result["frequency_days"] is None

def test_verified_currency_and_frequency():
    now=datetime(2026,11,18,tzinfo=timezone.utc)
    rs=[S(issued_at="2026-11-01T12:00:00+00:00",currency="RON",total_minor=1500),
        S(issued_at="2026-11-11T12:00:00+00:00",currency="RON",total_minor=2500),
        S(issued_at="2026-11-11T15:00:00+00:00",currency="EUR",total_minor=1000)]
    result=metrics(rs,[],Counter({"cafea":3}),now)
    assert result["verified_receipts"]==3
    assert result["verified_spend_minor"]==4000
    assert result["average_receipt_minor"]==2000
    assert result["purchase_days"]==2
    assert result["frequency_days"]==10
