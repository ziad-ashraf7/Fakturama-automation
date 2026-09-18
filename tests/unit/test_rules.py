from decimal import Decimal

import pytest

from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.outcomes import DomainValidationError, MasterDataConflict
from fakturama_automation.domain.rules import (
    MatchDecision,
    classify_exact_match,
    classify_vat_definition,
    line_total,
    payment_code,
    product_gross_price,
    reconcile_order,
)


def valid_order_data() -> dict[str, object]:
    return {
        "order_date": "2026-09-18",
        "external_reference": "PO-1042",
        "debtor": {
            "company": "Example GmbH",
            "alias": "EXAMPLE",
            "billing_address": {
                "street": "Main Street 1",
                "zip_code": "10115",
                "city": "Berlin",
                "country": "Germany",
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


def test_product_gross_price_uses_two_decimal_half_up_rounding() -> None:
    assert product_gross_price(Decimal("19.99"), Decimal(19)) == Decimal("23.79")


def test_line_total_applies_the_transaction_discount() -> None:
    assert line_total(Decimal(2), Decimal("19.99"), Decimal(10)) == Decimal("35.98")


def test_product_gross_price_does_not_apply_the_line_discount() -> None:
    gross_master_price = product_gross_price(Decimal("19.99"), Decimal(19))
    discounted_transaction_line = line_total(Decimal(1), Decimal("19.99"), Decimal(10))

    assert gross_master_price == Decimal("23.79")
    assert discounted_transaction_line == Decimal("17.99")


def test_exact_match_normalizes_only_case_outer_space_and_equivalent_whitespace() -> None:
    rows = [
        {"company": "  EXAMPLE   GmbH ", "zip": " 10115 "},
        {"company": "Example GmbH North", "zip": "10115"},
    ]

    decision = classify_exact_match(
        rows,
        {"company": "Example GmbH", "zip": "10115"},
        ("company", "zip"),
    )

    assert decision is MatchDecision.EXACT_MATCH


def test_similar_text_is_not_an_exact_match() -> None:
    decision = classify_exact_match(
        [{"company": "Example GmbH North"}],
        {"company": "Example GmbH"},
        ("company",),
    )

    assert decision is MatchDecision.NO_MATCH


def test_multiple_exact_rows_are_reported_as_ambiguous() -> None:
    decision = classify_exact_match(
        [{"sku": "SKU-1"}, {"sku": " sku-1 "}],
        {"sku": "SKU-1"},
        ("sku",),
    )

    assert decision is MatchDecision.MULTIPLE_MATCHES


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("Bank Transfer", "Credit transfer"),
        ("Credit Card", "Credit card"),
        ("SEPA Direct Debit", "SEPA direct debit"),
    ],
)
def test_payment_code_uses_the_assignment_mapping(method: str, expected: str) -> None:
    assert payment_code(method) == expected


def test_vat_definition_requires_exact_name_value_and_e_invoice_code() -> None:
    decision = classify_vat_definition(
        [{"name": "VAT 19%", "value": "19", "code": "S"}],
        Decimal(19),
    )

    assert decision is MatchDecision.EXACT_MATCH


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [("value", "7"), ("code", "Z")],
)
def test_conflicting_named_vat_definition_requires_manual_review(
    field: str,
    wrong_value: str,
) -> None:
    row = {"name": "VAT 19%", "value": "19", "code": "S"}
    row[field] = wrong_value

    with pytest.raises(MasterDataConflict):
        classify_vat_definition([row], Decimal(19))


def test_reconcile_order_rejects_a_source_line_total_mismatch() -> None:
    data = valid_order_data()
    data["items"][0]["source_total"] = "35.99"  # type: ignore[index]
    order = OrderInput.model_validate(data)

    with pytest.raises(DomainValidationError, match="SKU-1"):
        reconcile_order(order)


def test_reconcile_order_accepts_matching_source_totals() -> None:
    reconcile_order(OrderInput.model_validate(valid_order_data()))
