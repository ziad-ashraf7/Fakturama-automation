import pytest

from fakturama_automation.automation.app import complete_product_picker_selection
from fakturama_automation.domain.outcomes import AutomationFailure


def _selection_callbacks() -> tuple[list[str], object, object]:
    actions: list[str] = []
    press_enter = lambda: actions.append("enter")
    wait_for_close = lambda: True
    verify_inserted = lambda: True
    return actions, press_enter, wait_for_close, verify_inserted


def test_auto_selection_is_verified_without_enter_fallback() -> None:
    actions, press_enter, wait_for_close, verify_inserted = _selection_callbacks()

    result = complete_product_picker_selection(
        "CHR-ERG-01",
        picker_closed=True,
        candidates=(),
        press_enter=press_enter,
        wait_for_close=wait_for_close,
        verify_inserted=verify_inserted,
    )

    assert result == "auto"
    assert actions == []


def test_unique_exact_result_uses_enter_once_after_auto_selection_timeout() -> None:
    actions, press_enter, wait_for_close, verify_inserted = _selection_callbacks()

    result = complete_product_picker_selection(
        "CHR-ERG-01",
        picker_closed=False,
        candidates=("CHR-ERG-01",),
        press_enter=press_enter,
        wait_for_close=wait_for_close,
        verify_inserted=verify_inserted,
    )

    assert result == "enter"
    assert actions == ["enter"]


def test_ambiguous_results_fail_without_enter() -> None:
    actions, press_enter, wait_for_close, verify_inserted = _selection_callbacks()

    with pytest.raises(AutomationFailure, match="ambiguous"):
        complete_product_picker_selection(
            "CHR-ERG-01",
            picker_closed=False,
            candidates=("CHR-ERG-01", "CHR-ERG-02"),
            press_enter=press_enter,
            wait_for_close=wait_for_close,
            verify_inserted=verify_inserted,
        )

    assert actions == []


def test_enter_postcondition_failure_is_reported() -> None:
    actions, press_enter, wait_for_close, _ = _selection_callbacks()

    with pytest.raises(AutomationFailure, match="expected SKU"):
        complete_product_picker_selection(
            "CHR-ERG-01",
            picker_closed=False,
            candidates=("CHR-ERG-01",),
            press_enter=press_enter,
            wait_for_close=wait_for_close,
            verify_inserted=lambda: False,
        )

    assert actions == ["enter"]


def test_nonmatching_single_result_fails_without_enter() -> None:
    actions, press_enter, wait_for_close, verify_inserted = _selection_callbacks()

    with pytest.raises(AutomationFailure, match="does not match"):
        complete_product_picker_selection(
            "CHR-ERG-01",
            picker_closed=False,
            candidates=("CHR-ERG-02",),
            press_enter=press_enter,
            wait_for_close=wait_for_close,
            verify_inserted=verify_inserted,
        )

    assert actions == []
