from datetime import date
from types import SimpleNamespace

from fakturama_automation.automation.documents import _set_order_date


class _FakeDateEdit:
    def __init__(self) -> None:
        self.value = "Sep 19, 2026"
        self.element_info = SimpleNamespace(
            name="Date",
            control_type="Edit",
            class_name="Edit",
        )

    @property
    def iface_value(self):
        return SimpleNamespace(
            CurrentValue=self.value,
            SetValue=self._set_value,
        )

    def _set_value(self, value: str) -> None:
        self.value = value

    def window_text(self) -> str:
        return self.value

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True


class _FakeDateRoot:
    def __init__(self, date_edit: _FakeDateEdit) -> None:
        self.date_edit = date_edit

    def descendants(self, control_type: str):
        if control_type == "Edit":
            return [self.date_edit]
        return []


def test_set_order_date_uses_display_format_and_value_pattern() -> None:
    date_edit = _FakeDateEdit()

    _set_order_date(_FakeDateRoot(date_edit), date(2026, 7, 14))

    assert date_edit.value == "Jul 14, 2026"
