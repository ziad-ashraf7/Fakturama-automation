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
