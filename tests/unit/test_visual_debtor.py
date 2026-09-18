import pytest

from fakturama_automation.automation.visual_debtor import (
    VisualDebtorRow,
    exact_visual_matches,
    relative_click_point,
)
from fakturama_automation.domain.models import Address, Debtor
from fakturama_automation.domain.outcomes import AutomationFailure, MasterDataConflict


@pytest.fixture
def debtor() -> Debtor:
    return Debtor(
        company="Northstar Office GmbH",
        first_name="Marta",
        last_name="Klein",
        alias="NORTHSTAR-BERLIN",
        billing_address=Address(
            street="Friedrichstrasse 88",
            zip_code="10117",
            city="Berlin",
            country="Germany",
        ),
    )


def _row(**overrides: object) -> VisualDebtorRow:
    values: dict[str, object] = {
        "company": "Northstar Office GmbH",
        "first_name": "Marta",
        "last_name": "Klein",
        "zip_code": "10117",
        "city": "Berlin",
        "left": 10,
        "top": 20,
        "right": 300,
        "bottom": 45,
    }
    values.update(overrides)
    return VisualDebtorRow.model_validate(values)


def test_exact_visual_match_uses_visible_identity_fields(debtor: Debtor) -> None:
    rows = [_row(), _row(company="Other GmbH")]

    assert exact_visual_matches(rows, debtor) == [rows[0]]


def test_multiple_exact_visual_matches_raise_manual_review(debtor: Debtor) -> None:
    with pytest.raises(MasterDataConflict, match="Multiple exact debtor rows"):
        exact_visual_matches([_row(), _row(left=400, right=690)], debtor)




def test_company_ellipsis_is_presentation_truncation_not_fuzzy_match(debtor: Debtor) -> None:
    rows = [_row(company="Northstar Office ...")]

    assert exact_visual_matches(rows, debtor) == rows


def test_row_bounds_are_derived_from_detected_separators() -> None:
    from fakturama_automation.automation.visual_debtor import row_bounds_from_separators

    assert row_bounds_from_separators((778, 424), (19, 39, 59), 2) == [
        (0, 19, 778, 39),
        (0, 39, 778, 59),
    ]

def test_relative_click_point_requires_bounds_inside_capture() -> None:
    assert relative_click_point(_row(left=10, top=20, right=110, bottom=60), (200, 100)) == (
        60,
        40,
    )

    with pytest.raises(AutomationFailure, match="outside result-pane capture"):
        relative_click_point(_row(left=-1), (200, 100))

from PIL import Image, ImageDraw

from fakturama_automation.automation import visual_debtor


class _Edit:
    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True


class _Pane:
    def __init__(self, image: Image.Image) -> None:
        self.image = image
        self.clicked: tuple[int, int] | None = None

    def capture_as_image(self) -> Image.Image:
        return self.image

    def click_input(self, *, coords: tuple[int, int]) -> None:
        self.clicked = coords


class _Dialog:
    def __init__(self, edit: _Edit) -> None:
        self.edit = edit

    def descendants(self, *, control_type: str):
        return [self.edit] if control_type == "Edit" else []


def test_debtor_row_with_out_of_range_llm_bounds_uses_local_row_band(monkeypatch, debtor: Debtor) -> None:
    image = Image.new("RGB", (100, 30), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 5, 99, 5), fill="black")
    draw.line((0, 25, 99, 25), fill="black")
    pane = _Pane(image)
    rows = [
        visual_debtor.VisualDebtorRow(
            company="Northstar Office ...",
            first_name="Marta",
            last_name="Klein",
            zip_code="10117",
            city="Berlin",
            left=0,
            top=0,
            right=800,
            bottom=40,
        )
    ]
    monkeypatch.setattr(visual_debtor, "_result_pane", lambda dialog, search: pane)
    monkeypatch.setattr(visual_debtor, "_ocr_rows", lambda image, settings: rows)

    assert visual_debtor.select_debtor_row_visually(_Dialog(_Edit()), debtor, object()) is True
    assert pane.clicked == (50, 15)
