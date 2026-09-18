from decimal import Decimal

import pytest

from fakturama_automation.automation.app import (
    grid_key_path,
    normalize_grid_readback,
    value_for_grid_entry,
)


@pytest.mark.parametrize(
    ("start", "target", "expected"),
    [
        ("Qty", "U.Price", ("RIGHT",) * 6),
        ("U.Price", "VAT", ("LEFT",) * 2),
        ("VAT", "Discount", ("RIGHT",) * 2),
    ],
)
def test_grid_key_path_uses_verified_column_moves(
    start: str, target: str, expected: tuple[str, ...]
) -> None:
    assert grid_key_path(start, target) == expected


def test_grid_key_path_rejects_an_unverified_move() -> None:
    with pytest.raises(ValueError, match="No verified grid path"):
        grid_key_path("Qty", "VAT")


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("Qty", Decimal("7.00"), "7"),
        ("U.Price", Decimal("123.450"), "123.45"),
        ("Discount", Decimal(5), "-5"),
        ("Discount", Decimal(0), "0"),
    ],
)
def test_value_for_grid_entry_uses_plain_decimal_and_discount_sign(
    column: str, value: Decimal, expected: str
) -> None:
    assert value_for_grid_entry(column, value) == expected


@pytest.mark.parametrize(
    ("column", "displayed", "expected"),
    [
        ("Qty", "7.00", Decimal("7.00")),
        ("U.Price", "$123.45", Decimal("123.45")),
        ("Discount", "-5.00%", Decimal("5.00")),
        ("VAT", " Tax-free   (0.0%) ", "Tax-free (0.0%)"),
    ],
)
def test_normalize_grid_readback_handles_fakturama_presentation(
    column: str, displayed: str, expected: Decimal | str
) -> None:
    assert normalize_grid_readback(column, displayed) == expected
