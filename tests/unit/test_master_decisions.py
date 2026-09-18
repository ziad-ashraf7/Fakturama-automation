from decimal import Decimal

import pytest

from fakturama_automation.automation.masters import (
    ensure_payment_method,
    exact_decision,
    require_unambiguous,
)
from fakturama_automation.domain.outcomes import MasterDataConflict
from fakturama_automation.domain.rules import MatchDecision


def test_exact_decisions() -> None:
    rows = [{"sku": "A-1", "name": "Desk"}]
    assert exact_decision(rows, {"sku": "A-1"}, ("sku",)) is MatchDecision.EXACT_MATCH
    assert exact_decision([], {"sku": "A-1"}, ("sku",)) is MatchDecision.NO_MATCH
    with pytest.raises(MasterDataConflict):
        require_unambiguous(rows + rows, {"sku": "A-1"}, ("sku",), stage="product")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Bank Transfer", "Credit transfer"),
        ("Credit Card", "Credit card"),
        ("SEPA Direct Debit", "SEPA direct debit"),
    ],
)
def test_payment_mapping(source: str, expected: str) -> None:
    assert ensure_payment_method(None, source) == expected


def test_product_price_is_not_line_discounted() -> None:
    from fakturama_automation.domain.rules import product_gross_price

    assert product_gross_price(Decimal(250), Decimal(19)) == Decimal("297.50")
