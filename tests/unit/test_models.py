from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fakturama_automation.domain.models import (
    Address,
    Debtor,
    OrderInput,
    OrderItem,
    OrderTotals,
    Payment,
)


def valid_order_data() -> dict[str, object]:
    return {
        "order_date": "2026-09-18",
        "external_reference": "PO-1042",
        "debtor": {
            "company": "Example GmbH",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "alias": "EXAMPLE",
            "billing_address": {
                "street": "Main Street 1",
                "zip_code": "10115",
                "city": "Berlin",
                "country": "Germany",
                "email": "ada@example.test",
                "telephone": "+49 30 123456",
            },
        },
        "payment": {"method": "Bank Transfer", "status": "UNPAID"},
        "items": [
            {
                "sku": "SKU-1",
                "description": "Widget",
                "quantity": "2",
                "unit_net": "19.99",
                "vat_percent": "19",
                "discount_percent": "10",
                "source_total": "35.98",
            }
        ],
        "totals": {"net": "35.98", "vat": "6.84", "gross": "42.82"},
    }


def test_valid_order_keeps_financial_values_as_decimals() -> None:
    order = OrderInput.model_validate(valid_order_data())

    assert order.order_date == date(2026, 9, 18)
    assert order.items[0].quantity == Decimal(2)
    assert order.items[0].unit_net == Decimal("19.99")
    assert order.items[0].vat_percent == Decimal(19)
    assert order.items[0].discount_percent == Decimal(10)
    assert order.items[0].source_total == Decimal("35.98")
    assert order.totals.net == Decimal("35.98")
    assert order.totals.vat == Decimal("6.84")
    assert order.totals.gross == Decimal("42.82")


@pytest.mark.parametrize(
    "field",
    ["quantity", "unit_net", "vat_percent", "discount_percent", "source_total"],
)
def test_item_rejects_a_missing_required_financial_value(field: str) -> None:
    item = valid_order_data()["items"][0].copy()  # type: ignore[index, union-attr]
    item.pop(field)

    with pytest.raises(ValidationError):
        OrderItem.model_validate(item)


def test_order_rejects_an_invalid_date() -> None:
    data = valid_order_data()
    data["order_date"] = "18/09/2026"

    with pytest.raises(ValidationError):
        OrderInput.model_validate(data)


def test_item_rejects_a_negative_quantity() -> None:
    item = valid_order_data()["items"][0].copy()  # type: ignore[index, union-attr]
    item["quantity"] = "-1"

    with pytest.raises(ValidationError):
        OrderItem.model_validate(item)


def test_payment_date_is_optional_and_parsed_only_when_supplied() -> None:
    unpaid = Payment(method="Credit Card", status="UNPAID")
    paid = Payment(method="Credit Card", status="PAID", payment_date="2026-09-19")

    assert unpaid.payment_date is None
    assert paid.payment_date == date(2026, 9, 19)


def test_order_totals_distinguish_omitted_values_from_explicit_zero() -> None:
    omitted = OrderTotals(net="10.00", vat="1.90", gross="11.90")
    explicit = OrderTotals(
        net="10.00",
        vat="1.90",
        gross="11.90",
        discount_percent="0",
        shipping="0.00",
    )

    assert omitted.discount_percent is None
    assert omitted.shipping is None
    assert explicit.discount_percent == Decimal(0)
    assert explicit.shipping == Decimal("0.00")


def test_domain_models_accept_their_typed_nested_values() -> None:
    address = Address(street="Main Street 1", zip_code="10115", city="Berlin", country="DE")
    debtor = Debtor(
        company="Example GmbH",
        first_name="Ada",
        last_name="Lovelace",
        alias="EXAMPLE",
        billing_address=address,
    )

    assert debtor.billing_address is address
    assert debtor.delivery_address is None
