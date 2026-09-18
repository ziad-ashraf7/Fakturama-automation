import pytest
from PIL import Image, ImageDraw

from fakturama_automation.automation.visual_items import (
    detect_row_bands,
    item_cell_for_sku,
    markdown_item_rows,
    row_band_for_sku,
)
from fakturama_automation.domain.outcomes import AutomationFailure, MasterDataConflict


def test_markdown_item_rows_extracts_exact_item_number_column() -> None:
    markdown = """| Pos. | Qty. | Item No. | Name |
| --- | --- | --- | --- |
| 1 | 1.00 | CHR-ERG-01 | Ergonomic Chair |
| Check an item from the list | | | |
| Total Gross | | | |
"""
    assert markdown_item_rows(markdown) == ["CHR-ERG-01"]


def test_markdown_item_rows_rejects_duplicate_exact_skus() -> None:
    markdown = """| Pos. | Item No. |
| --- | --- |
| 1 | CHR-ERG-01 |
| 2 | CHR-ERG-01 |
"""
    image = Image.new("RGB", (100, 30), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 9, 99, 9), fill="black")
    draw.line((0, 19, 99, 19), fill="black")
    with pytest.raises(MasterDataConflict):
        row_band_for_sku(image, markdown, "CHR-ERG-01")


def test_row_band_for_sku_maps_markdown_row_to_dynamic_band() -> None:
    markdown = """| Pos. | Item No. |
| --- | --- |
| 1 | CHR-ERG-01 |
"""
    image = Image.new("RGB", (100, 30), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 9, 99, 9), fill="black")
    draw.line((0, 19, 99, 19), fill="black")
    assert row_band_for_sku(image, markdown, "CHR-ERG-01") == (0, 10, 100, 19)


def test_item_cell_for_sku_maps_markdown_column_to_dynamic_cell() -> None:
    markdown = """| Pos. | Item No. | Name |
| --- | --- | --- |
| 1 | CHR-ERG-01 | Chair |
"""
    image = Image.new("RGB", (100, 30), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 9, 99, 9), fill="black")
    draw.line((0, 19, 99, 19), fill="black")
    draw.line((20, 0, 20, 19), fill="black")
    draw.line((50, 0, 50, 19), fill="black")
    assert item_cell_for_sku(image, markdown, "CHR-ERG-01") == (20, 10, 50, 19)


def test_detect_row_bands_requires_enough_dynamic_separators() -> None:
    image = Image.new("RGB", (100, 30), "white")
    with pytest.raises(AutomationFailure):
        detect_row_bands(image, 1)
