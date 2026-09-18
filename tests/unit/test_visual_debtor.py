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


def test_relative_click_point_requires_bounds_inside_capture() -> None:
    assert relative_click_point(_row(left=10, top=20, right=110, bottom=60), (200, 100)) == (
        60,
        40,
    )

    with pytest.raises(AutomationFailure, match="outside result-pane capture"):
        relative_click_point(_row(left=-1), (200, 100))
