"""Narrow visual fallback for activating a visible opaque Items-grid row."""

from __future__ import annotations

import base64
import io
import re
from collections import Counter
from itertools import pairwise
from typing import Any

from mistralai.client import Mistral
from mistralai.client.models import ImageURLChunk

from fakturama_automation.automation.app import _automation_failure
from fakturama_automation.config import Settings
from fakturama_automation.domain.outcomes import MasterDataConflict


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(
                _normalize(cell) in {"item no.", "sku", "item number"}
                for cell in _markdown_cells(line)
            )
        ),
        None,
    )
    if header_index is None:
        raise _automation_failure("Items OCR markdown has no Item No. column")
    headers = _markdown_cells(lines[header_index])
    for index, cell in enumerate(headers):
        if _normalize(cell) in {"item no.", "sku", "item number"}:
            item_column = index
            break
    else:
        raise _automation_failure("Items OCR markdown has no Item No. column")

    data_rows: list[list[str]] = []
    for line in lines[header_index + 1 :]:
        cells = _markdown_cells(line)
        if not cells or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if item_column < len(cells) and cells[item_column].strip():
            data_rows.append(cells)
    return headers, data_rows


def markdown_item_rows(markdown: str) -> list[str]:
    """Extract visible data-row SKUs from the normal OCR markdown table."""

    headers, rows = _markdown_table(markdown)
    item_column = next(
        index
        for index, cell in enumerate(headers)
        if _normalize(cell) in {"item no.", "sku", "item number"}
    )
    return [row[item_column].strip() for row in rows if item_column < len(row)]


def _horizontal_separators(image: Any) -> tuple[int, ...]:
    gray = image.convert("L")
    width = gray.width
    threshold = max(1, int(width * 0.95))
    candidates = [
        y
        for y in range(gray.height)
        if sum(1 for x in range(width) if gray.getpixel((x, y)) < 220) >= threshold
    ]
    groups: list[list[int]] = []
    for y in candidates:
        if not groups or y > groups[-1][-1] + 1:
            groups.append([y])
        else:
            groups[-1].append(y)
    return tuple((group[0] + group[-1]) // 2 for group in groups)


def detect_row_bands(image: Any, row_count: int) -> list[tuple[int, int, int, int]]:
    """Detect current visible data-row bands between horizontal grid separators."""

    if row_count <= 0:
        raise _automation_failure("Items OCR returned no data rows")
    separators = _horizontal_separators(image)
    bands = [
        (0, top + 1, image.width, bottom)
        for top, bottom in pairwise(separators)
        if bottom > top + 2
    ]
    if len(bands) < row_count:
        raise _automation_failure(
            f"Could not detect {row_count} visible Items-grid row bands; "
            f"detected {len(bands)}"
        )
    return bands[:row_count]


def _vertical_separators(image: Any) -> tuple[int, ...]:
    gray = image.convert("L")
    horizontal = _horizontal_separators(image)
    if not horizontal:
        raise _automation_failure("Could not detect the Items table extent")
    table_height = horizontal[-1] + 1
    dominant_threshold = max(1, int(table_height * 0.8))
    candidates: list[int] = []
    for x in range(gray.width):
        counts = Counter(gray.getpixel((x, y)) for y in range(table_height))
        dominant, count = counts.most_common(1)[0]
        if count >= dominant_threshold and dominant < 240:
            candidates.append(x)
    groups: list[list[int]] = []
    for x in candidates:
        if not groups or x > groups[-1][-1] + 1:
            groups.append([x])
        else:
            groups[-1].append(x)
    max_separator_width = max(2, int(gray.width * 0.02))
    return tuple(
        (group[0] + group[-1]) // 2
        for group in groups
        if len(group) <= max_separator_width
    )


def _item_column(headers: list[str]) -> int:
    for index, cell in enumerate(headers):
        if _normalize(cell) in {"item no.", "sku", "item number"}:
            return index
    raise _automation_failure("Items OCR markdown has no Item No. column")


def _column_index(headers: list[str], column: str) -> int:
    expected = _normalize(column).rstrip(".")
    aliases = {
        "item no": {"item no", "sku", "item number"},
        "qty": {"qty", "quantity"},
        "u.price": {"u.price", "unit price"},
        "vat": {"vat"},
        "discount": {"discount"},
        "price": {"price"},
    }
    accepted = aliases.get(expected, {expected})
    for index, header in enumerate(headers):
        if _normalize(header).rstrip(".") in accepted:
            return index
    raise _automation_failure(f"Items OCR markdown has no {column!r} column")


def cell_for_sku(
    image: Any, markdown: str, sku: str, column: str
) -> tuple[int, int, int, int]:
    """Map one exact markdown SKU row to a dynamically detected cell."""

    headers, rows = _markdown_table(markdown)
    item_column = _item_column(headers)
    column_index = _column_index(headers, column)
    matches = [
        index
        for index, row in enumerate(rows)
        if item_column < len(row) and _normalize(row[item_column]) == _normalize(sku)
    ]
    if len(matches) > 1:
        raise MasterDataConflict("Multiple exact product rows", stage="product")
    if not matches:
        raise _automation_failure(f"Visible product row {sku!r} was not verified")
    _row_left, row_top, _row_right, row_bottom = detect_row_bands(image, len(rows))[matches[0]]
    separators = _vertical_separators(image)
    boundaries = [0, *separators, image.width]
    if column_index + 1 >= len(boundaries):
        raise _automation_failure(f"Could not detect {column!r} column in current grid image")
    return (
        boundaries[column_index],
        row_top,
        boundaries[column_index + 1],
        row_bottom,
    )


def row_band_for_sku(
    image: Any, markdown: str, sku: str
) -> tuple[int, int, int, int]:
    """Map one exact markdown SKU row to its locally detected image band."""

    headers, rows = _markdown_table(markdown)
    item_column = _item_column(headers)
    matches = [
        index
        for index, row in enumerate(rows)
        if item_column < len(row) and _normalize(row[item_column]) == _normalize(sku)
    ]
    if len(matches) > 1:
        raise MasterDataConflict("Multiple exact product rows", stage="product")
    if not matches:
        raise _automation_failure(f"Visible product row {sku!r} was not verified")
    bands = detect_row_bands(image, len(rows))
    return bands[matches[0]]


def cell_text_for_sku(markdown: str, sku: str, column: str) -> str:
    headers, rows = _markdown_table(markdown)
    item_column = _item_column(headers)
    column_index = _column_index(headers, column)
    matches = [
        row
        for row in rows
        if item_column < len(row) and _normalize(row[item_column]) == _normalize(sku)
    ]
    if len(matches) > 1:
        raise MasterDataConflict("Multiple exact product rows", stage="product")
    if not matches:
        raise _automation_failure(f"Visible product row {sku!r} was not verified")
    row = matches[0]
    if column_index >= len(row):
        raise _automation_failure(f"Visible product row {sku!r} has no {column!r} value")
    return row[column_index].strip()


def read_item_cell_visually(
    grid: Any, sku: str, column: str, settings: Settings
) -> str:
    image = grid.capture_as_image()
    return cell_text_for_sku(_ocr_markdown(image, settings), sku, column)


def item_cell_for_sku(
    image: Any, markdown: str, sku: str
) -> tuple[int, int, int, int]:
    """Map one exact markdown SKU row to its dynamically detected Item No. cell."""

    return cell_for_sku(image, markdown, sku, "Item No.")



def _ocr_markdown(image: Any, settings: Settings) -> str:
    api_key = settings.mistral_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise _automation_failure("MISTRAL_API_KEY is required for Items-grid OCR")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    try:
        response = Mistral(api_key=api_key.get_secret_value()).ocr.process(
            model=settings.mistral_model,
            document=ImageURLChunk(image_url=f"data:image/png;base64,{encoded}"),
        )
        markdown = "\n\n".join(
            getattr(page, "markdown", "") or ""
            for page in (getattr(response, "pages", []) or [])
        ).strip()
        if not markdown:
            markdown = str(getattr(response, "markdown", "") or "").strip()
        if not markdown:
            raise TypeError("Mistral returned no OCR markdown")
        return markdown
    except Exception as error:
        raise _automation_failure("Mistral Items-grid OCR failed") from error


def select_item_row_visually(grid: Any, sku: str, settings: Settings) -> bool:
    """Select one exact visible SKU cell using OCR text and local image geometry."""

    image = grid.capture_as_image()
    markdown = _ocr_markdown(image, settings)
    left, top, right, bottom = cell_for_sku(image, markdown, sku, "Item No.")
    grid.click_input(coords=((left + right) // 2, (top + bottom) // 2))
    return True


def activate_item_cell_visually(
    grid: Any, sku: str, column: str, settings: Settings
) -> tuple[int, int, int, int]:
    """Click one exact SKU row's current cell using local OCR geometry."""

    image = grid.capture_as_image()
    markdown = _ocr_markdown(image, settings)
    cell = cell_for_sku(image, markdown, sku, column)
    left, top, right, bottom = cell
    grid.click_input(coords=((left + right) // 2, (top + bottom) // 2))
    return cell
