"""Narrow visual fallback for Fakturama's opaque debtor result table."""

from __future__ import annotations

import base64
import io
import json
from typing import Any

from mistralai.client import Mistral
from mistralai.client.models import ImageURLChunk
from mistralai.extra import response_format_from_pydantic_model
from pydantic import BaseModel, ConfigDict, ValidationError

from fakturama_automation.automation.app import (
    _automation_failure,
    _visible,
)
from fakturama_automation.config import Settings
from fakturama_automation.domain.models import Debtor
from fakturama_automation.domain.outcomes import MasterDataConflict


class VisualDebtorRow(BaseModel):
    """One OCR-described visible row, with bounds relative to the captured Pane."""

    model_config = ConfigDict(extra="forbid")

    company: str = ""
    first_name: str = ""
    last_name: str = ""
    zip_code: str = ""
    city: str = ""
    left: int
    top: int
    right: int
    bottom: int


class VisualDebtorTable(BaseModel):
    """Structured OCR response for the currently visible debtor rows."""

    model_config = ConfigDict(extra="forbid")

    rows: list[VisualDebtorRow]


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def exact_visual_matches(rows: list[VisualDebtorRow], debtor: Debtor) -> list[VisualDebtorRow]:
    """Return rows matching every non-empty identity field visible in the source."""

    expected = {
        "company": debtor.company,
        "first_name": debtor.first_name or "",
        "last_name": debtor.last_name or "",
        "zip_code": debtor.billing_address.zip_code,
        "city": debtor.billing_address.city,
    }
    matches = [
        row
        for row in rows
        if all(
            not expected[field] or _normalize(getattr(row, field)) == _normalize(expected[field])
            for field in expected
        )
    ]
    if len(matches) > 1:
        raise MasterDataConflict("Multiple exact debtor rows", stage="debtor")
    return matches


def relative_click_point(row: VisualDebtorRow, image_size: tuple[int, int]) -> tuple[int, int]:
    """Validate an OCR box and return its center in the captured Pane coordinates."""

    width, height = image_size
    if not (
        0 <= row.left < row.right <= width
        and 0 <= row.top < row.bottom <= height
    ):
        raise _automation_failure("OCR debtor row bounds are outside result-pane capture")
    return ((row.left + row.right) // 2, (row.top + row.bottom) // 2)


def _result_pane(dialog: Any, search: Any) -> Any:
    search_rect = search.element_info.rectangle
    dialog_rect = dialog.element_info.rectangle
    candidates: list[Any] = []
    seen: set[tuple[int | None, int, int, int, int]] = set()
    for pane in dialog.descendants(control_type="Pane"):
        if not _visible(pane) or pane.element_info.class_name != "SWT_Window0":
            continue
        rect = pane.element_info.rectangle
        key = (pane.handle, rect.left, rect.top, rect.right, rect.bottom)
        if key in seen:
            continue
        seen.add(key)
        if (
            rect.top >= search_rect.bottom
            and rect.left >= dialog_rect.left
            and rect.right <= dialog_rect.right
            and rect.bottom <= dialog_rect.bottom
            and rect.right > rect.left
            and rect.bottom > rect.top
        ):
            candidates.append(pane)
    if not candidates:
        raise _automation_failure("Could not locate the current debtor result Pane")
    return max(
        candidates,
        key=lambda pane: (
            pane.element_info.rectangle.right - pane.element_info.rectangle.left
        )
        * (pane.element_info.rectangle.bottom - pane.element_info.rectangle.top),
    )


def _ocr_rows(image: Any, settings: Settings) -> list[VisualDebtorRow]:
    api_key = settings.mistral_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise _automation_failure("MISTRAL_API_KEY is required for debtor visual OCR")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    prompt = """Read only the visible debtor rows in this cropped table image.
Return every visible row. The coordinates must be pixel bounds relative to the image's
top-left corner and cover the complete row. Use empty strings when a cell is not readable;
do not infer values. The visible columns are Company, First Name, Name, ZIP, and City.
"""
    try:
        response = Mistral(api_key=api_key.get_secret_value()).ocr.process(
            model=settings.mistral_model,
            document=ImageURLChunk(image_url=f"data:image/png;base64,{encoded}"),
            document_annotation_format=response_format_from_pydantic_model(VisualDebtorTable),
            document_annotation_prompt=prompt,
        )
        annotation = response.document_annotation
        if not isinstance(annotation, str):
            raise TypeError("Mistral returned no structured debtor-row annotation")
        payload = json.loads(annotation)
        return VisualDebtorTable.model_validate(payload).rows
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _automation_failure("Mistral debtor visual OCR returned unusable rows") from error
    except Exception as error:
        raise _automation_failure("Mistral debtor visual OCR failed") from error


def select_debtor_row_visually(dialog: Any, debtor: Debtor, settings: Settings) -> bool:
    """Select one exact debtor row in the opaque SWT result Pane."""

    searches = [edit for edit in dialog.descendants(control_type="Edit") if _visible(edit)]
    if len(searches) != 1:
        raise _automation_failure(f"Expected one debtor search field, found {len(searches)}")
    pane = _result_pane(dialog, searches[0])
    image = pane.capture_as_image()
    rows = _ocr_rows(image, settings)
    matches = exact_visual_matches(rows, debtor)
    if not matches:
        return False
    point = relative_click_point(matches[0], image.size)
    pane.click_input(coords=point)
    return True
