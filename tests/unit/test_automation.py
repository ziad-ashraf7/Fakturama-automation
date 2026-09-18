from decimal import Decimal

import pytest

from fakturama_automation.automation.app import (
    escape_keyboard_text,
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


def test_escape_keyboard_text_preserves_literal_sku_characters() -> None:
    assert escape_keyboard_text("SKU+{A}%") == "SKU{+}{{}A{}}{%}"

class _FakeInfo:
    def __init__(self, name: str, process_id: int) -> None:
        self.name = name
        self.process_id = process_id


class _FakeControl:
    def __init__(self, name: str, process_id: int, visible: bool = True) -> None:
        self.element_info = _FakeInfo(name, process_id)
        self._visible = visible

    def is_visible(self) -> bool:
        return self._visible

    def is_enabled(self) -> bool:
        return self._visible


class _FakeWindow(_FakeControl):
    def __init__(self, process_id: int, descendants: list[_FakeControl]) -> None:
        super().__init__("Fakturama", process_id)
        self._descendants = descendants

    def descendants(self, **_: object) -> list[_FakeControl]:
        return self._descendants


class _FakeDesktop:
    def windows(self) -> list[_FakeControl]:
        return []


def test_product_picker_can_be_found_as_fakturama_child_window() -> None:
    from fakturama_automation.automation.app import FakturamaApp

    picker = _FakeControl("Select a product", 7)
    app = object.__new__(FakturamaApp)
    app.window = _FakeWindow(7, [picker])
    app.desktop = _FakeDesktop()

    assert app._picker() is picker
