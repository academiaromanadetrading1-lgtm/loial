"""Regression coverage for AI simulation inputs."""
import json
from decimal import Decimal

import pytest

from loial_financial_simulation import calculate, enrich_answer, LABELS


def base():
    return {"currency": "RON", "basis": "Monthly, comparable VAT basis",
            "transactions": 100, "average_ticket": 50,
            "variable_cost": 2000, "fixed_cost": 1000,
            "target_pct": 30, "scenarios": []}


@pytest.mark.parametrize("count", [0.5, 100.1, -1, True, "100"])
def test_reject_invalid_transaction_counts(count):
    spec = base()
    spec["transactions"] = count
    with pytest.raises(ValueError):
        calculate(spec, "RON")


def test_integer_counts_and_exact_target():
    result = calculate(base(), "RON")
    assert result["revenue"] == Decimal("5000")
    assert result["profit"] == Decimal("2000")
    assert result["target"] == Decimal("2600")
    assert result["target_sales"] == Decimal("1000")


@pytest.mark.parametrize("basis", ["|", "\x00", "\n|\t"])
def test_empty_normalized_basis_is_rejected(basis):
    spec = base()
    spec["basis"] = basis
    with pytest.raises(ValueError):
        calculate(spec, "RON")


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_keys_are_rejected(nested):
    spec = base()
    if nested:
        spec["scenarios"] = [{"name":"A","assumption":"Test",
            "revenue_delta":100,"variable_cost_delta":40,"fixed_cost_delta":0}]
        payload = json.dumps(spec).replace('"revenue_delta": 100', '"revenue_delta": 100, "revenue_delta": 1000')
    else:
        payload = json.dumps(spec).replace('"fixed_cost": 1000', '"fixed_cost": 1000, "fixed_cost": 1')
    answer = "```loial-simulation\n" + payload + "\n```"
    assert enrich_answer(answer, "RON", "en") == LABELS["en"][18]
    assert enrich_answer(answer, "RON", "en", truncated=True) == ""
