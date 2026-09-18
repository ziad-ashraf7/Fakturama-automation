"""Pure Decimal calculations and deterministic master-data decisions."""

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.outcomes import DomainValidationError, MasterDataConflict

MONEY_QUANTUM = Decimal("0.01")
ONE_HUNDRED = Decimal(100)


class MatchDecision(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    NO_MATCH = "NO_MATCH"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _plain_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def product_gross_price(unit_net: Decimal, vat_percent: Decimal) -> Decimal:
    return _money(unit_net * (Decimal(1) + vat_percent / ONE_HUNDRED))


def line_total(
    quantity: Decimal,
    unit_net: Decimal,
    discount_percent: Decimal,
) -> Decimal:
    return _money(quantity * unit_net * (Decimal(1) - discount_percent / ONE_HUNDRED))


def classify_exact_match(
    rows: list[dict[str, str]],
    expected: dict[str, str],
    fields: tuple[str, ...],
) -> MatchDecision:
    matches = [
        row
        for row in rows
        if all(
            field in row
            and field in expected
            and _normalized(row[field]) == _normalized(expected[field])
            for field in fields
        )
    ]
    if not matches:
        return MatchDecision.NO_MATCH
    if len(matches) == 1:
        return MatchDecision.EXACT_MATCH
    return MatchDecision.MULTIPLE_MATCHES


def payment_code(method: str) -> str:
    mappings = {
        _normalized("Bank Transfer"): "Credit transfer",
        _normalized("Credit Card"): "Credit card",
        _normalized("SEPA Direct Debit"): "SEPA direct debit",
    }
    try:
        return mappings[_normalized(method)]
    except KeyError as error:
        raise DomainValidationError(
            f"Unsupported payment method: {method}", stage="payment_method"
        ) from error


def classify_vat_definition(
    rows: list[dict[str, str]],
    vat_percent: Decimal,
) -> MatchDecision:
    percentage = _plain_decimal(vat_percent)
    expected_name = f"VAT {percentage}%"
    named_rows = [
        row for row in rows if _normalized(row.get("name", "")) == _normalized(expected_name)
    ]
    if not named_rows:
        return MatchDecision.NO_MATCH

    exact_rows = [
        row
        for row in named_rows
        if _normalized(row.get("value", "").removesuffix("%")) == _normalized(percentage)
        and _normalized(row.get("code", "")) == "s"
    ]
    if len(exact_rows) != len(named_rows):
        raise MasterDataConflict(f"Conflicting definition for {expected_name}", stage="vat")
    if len(exact_rows) == 1:
        return MatchDecision.EXACT_MATCH
    return MatchDecision.MULTIPLE_MATCHES


def reconcile_order(order: OrderInput) -> None:
    calculated_lines: list[tuple[Decimal, Decimal]] = []
    for item in order.items:
        calculated_total = line_total(item.quantity, item.unit_net, item.discount_percent)
        if calculated_total != _money(item.source_total):
            raise DomainValidationError(
                f"Source total mismatch for item {item.sku}: "
                f"expected {calculated_total}, got {item.source_total}",
                stage="reconciliation",
            )
        calculated_lines.append((calculated_total, item.vat_percent))

    order_discount = order.totals.discount_percent or Decimal(0)
    discount_factor = Decimal(1) - order_discount / ONE_HUNDRED
    shipping = order.totals.shipping or Decimal(0)
    expected_net = _money(
        sum((total for total, _ in calculated_lines), Decimal(0)) * discount_factor
    )
    expected_net = _money(expected_net + shipping)
    expected_vat = _money(
        sum(
            (
                _money(total * discount_factor * vat_percent / ONE_HUNDRED)
                for total, vat_percent in calculated_lines
            ),
            Decimal(0),
        )
    )
    expected_gross = _money(expected_net + expected_vat)

    expected = (expected_net, expected_vat, expected_gross)
    supplied = tuple(
        _money(value) for value in (order.totals.net, order.totals.vat, order.totals.gross)
    )
    if supplied != expected:
        raise DomainValidationError(
            f"Source order totals mismatch: expected net/VAT/gross {expected}, got {supplied}",
            stage="reconciliation",
        )
