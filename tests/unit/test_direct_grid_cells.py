from PIL import Image, ImageDraw

from fakturama_automation.automation import visual_items


def test_cell_for_sku_maps_requested_u_price_column_to_dynamic_cell() -> None:
    markdown = """| Qty. | Item No. | VAT | U.Price |
| --- | --- | --- | --- |
| 1.00 | CHR-ERG-01 | VAT 19% | 250.00 |
"""
    image = Image.new("RGB", (100, 30), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 9, 99, 9), fill="black")
    draw.line((0, 19, 99, 19), fill="black")
    draw.line((20, 0, 20, 19), fill="black")
    draw.line((50, 0, 50, 19), fill="black")
    draw.line((70, 0, 70, 19), fill="black")

    assert visual_items.cell_for_sku(
        image, markdown, "CHR-ERG-01", "U.Price"
    ) == (70, 10, 100, 19)


def test_edit_grid_values_skips_vat_dropdown_when_inherited_value_matches(
    monkeypatch,
) -> None:
    from decimal import Decimal

    from fakturama_automation.automation.app import OrderView

    view = object.__new__(OrderView)

    def edit_numeric(sku: str, column: str, value: Decimal) -> str:
        del sku
        return str(value)

    def read_visible_cell(sku: str, column: str) -> str:
        del sku
        if column == "VAT":
            return "VAT 19% (19.0%)"
        return ""

    def fail_activation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("VAT dropdown should not be opened")

    monkeypatch.setattr(view, "_edit_direct_numeric", edit_numeric)
    monkeypatch.setattr(view, "_read_visible_cell", read_visible_cell, raising=False)
    monkeypatch.setattr(view, "_activate_grid_cell", fail_activation)
    monkeypatch.setattr(view, "_edit_vat", fail_activation)

    result = view.edit_grid_values(
        sku="MAT-DESK-02",
        quantity=Decimal(3),
        unit_price=Decimal("40.00"),
        vat="VAT 19%",
        discount_percent=Decimal(0),
    )

    assert result["VAT"] == "VAT 19% (19.0%)"
