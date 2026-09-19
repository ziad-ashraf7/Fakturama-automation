from datetime import date
from types import SimpleNamespace

import pytest

from fakturama_automation.automation import documents


class _FakeDateEdit:
    def __init__(self) -> None:
        self.value = "Sep 19, 2026"
        self.segment = "month"
        self.committed = False
    @property
    def iface_value(self):
        return SimpleNamespace(CurrentValue=self.value)

    def window_text(self) -> str:
        return self.value

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    @property
    def element_info(self):
        return SimpleNamespace(
            name="Date",
            control_type="Edit",
            class_name="Edit",
            rectangle=SimpleNamespace(width=lambda: 100, height=lambda: 20),
        )

    def set_focus(self) -> None:
        pass

    def click_input(self, **kwargs: object) -> None:
        del kwargs


class _FakeDateRoot:
    def __init__(self, date_edit: _FakeDateEdit) -> None:
        self.date_edit = date_edit

    def descendants(self, control_type: str):
        if control_type == "Edit":
            return [self.date_edit]
        return []


def test_set_order_date_commits_segmented_value_before_focus_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    date_edit = _FakeDateEdit()
    root = _FakeDateRoot(date_edit)
    sent: list[str] = []

    def fake_send_keys(keys: str, **kwargs: object) -> None:
        del kwargs
        sent.append(keys)
        if keys == "{HOME}":
            date_edit.segment = "month"
        elif keys == "{ENTER}":
            date_edit.segment = {"month": "day", "day": "year", "year": "done"}[date_edit.segment]
            if date_edit.segment == "done":
                date_edit.committed = True
        elif date_edit.segment == "month":
            date_edit.value = "Jul 19, 2026"
        elif date_edit.segment == "day" or date_edit.segment == "year":
            date_edit.value = "Jul 14, 2026"

    monkeypatch.setattr(documents.keyboard, "send_keys", fake_send_keys)

    documents._set_order_date(root, date(2026, 7, 14))

    assert sent == ["{HOME}", "7", "{ENTER}", "14", "{ENTER}", "2026", "{ENTER}"]
    assert date_edit.value == "Jul 14, 2026"
    assert date_edit.committed is True

    date_edit.segment = "blurred"
    assert date_edit.value == "Jul 14, 2026"
