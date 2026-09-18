from datetime import date
from decimal import Decimal

from fakturama_automation.automation.documents import expected_line_values, order_level_values
from fakturama_automation.domain.models import OrderInput


def make_order(totals: dict[str, str | None]) -> OrderInput:
    return OrderInput.model_validate(
        {
            "order_date": date(2026, 9, 18),
            "external_reference": "PO-1",
            "debtor": {
                "company": "Example",
                "alias": "EX",
                "billing_address": {
                    "street": "Street 1",
                    "zip_code": "10115",
                    "city": "Berlin",
                    "country": "DE",
                },
            },
            "payment": {"method": "Bank Transfer", "status": "UNPAID"},
            "items": [
                {
                    "sku": "A",
                    "description": "Item",
                    "quantity": "2",
                    "unit_net": "10",
                    "vat_percent": "19",
                    "discount_percent": "5",
                    "source_total": "19",
                }
            ],
            "totals": totals,
        }
    )


def test_order_defaults_preserve_explicit_values() -> None:
    order = make_order({"net": "19", "vat": "3.61", "gross": "22.61"})
    assert order_level_values(order) == (Decimal(0), Decimal(0))
    order = make_order(
        {
            "net": "19",
            "vat": "3.61",
            "gross": "22.61",
            "discount_percent": "5",
            "shipping": "12.50",
        }
    )
    assert order_level_values(order) == (Decimal(5), Decimal("12.50"))


def test_expected_line_value_uses_decimal_line_rule() -> None:
    order = make_order({"net": "19", "vat": "3.61", "gross": "22.61"})
    assert expected_line_values(order) == {"A": Decimal("19.00")}
