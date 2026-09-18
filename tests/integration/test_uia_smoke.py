"""Opt-in UIA smoke and controlled unsaved-order risk probe."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from fakturama_automation.config import Settings

pytestmark = pytest.mark.uia


@pytest.fixture(scope="module")
def uia_enabled() -> None:
    if os.environ.get("RUN_UIA_TESTS") != "1":
        pytest.skip("set RUN_UIA_TESTS=1 to run against a controlled Fakturama session")


def test_fakturama_window_and_new_order_action_are_available(uia_enabled: None) -> None:
    from fakturama_automation.automation.app import FakturamaApp

    app = FakturamaApp.attach_or_start(Settings())

    assert app.window.window_text().startswith("Fakturama")
    assert app.window.element_info.class_name == "SWT_Window0"
    assert app.find_unique("Create: New Order", "Button").is_enabled()


def test_unsaved_order_sections_and_items_grid_probe(uia_enabled: None) -> None:
    from fakturama_automation.automation.app import FakturamaApp, probe_items_grid

    app = FakturamaApp.attach_or_start(Settings())
    order_view = app.open_unsaved_order()
    try:
        assert order_view.find_section_image("Addresses")
        assert order_view.find_section_image("Items")

        order_view.insert_unique_product("UIA-PROBE-001")
        evidence = probe_items_grid(
            order_view,
            quantity=Decimal(7),
            unit_price=Decimal("123.45"),
            vat="Tax-free (0.0%)",
            discount_percent=Decimal(5),
        )

        assert evidence.verified, evidence
        assert evidence.column_order == ("Qty", "U.Price", "VAT", "Discount")
        assert set(evidence.read_back_values) == set(evidence.column_order)
    finally:
        app.close_unsaved_editor()
