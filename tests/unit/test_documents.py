from types import SimpleNamespace

from fakturama_automation.automation.documents import _select_net_price_mode


class _FakeCombo:
    def __init__(self, value: str) -> None:
        self.element_info = SimpleNamespace(
            name="",
            control_type="ComboBox",
            class_name="ComboBox",
        )
        self.value = value

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    @property
    def iface_value(self):
        return SimpleNamespace(CurrentValue=self.value)

    def select(self, value: str) -> None:
        self.value = value


class _FakeRoot:
    def __init__(self, combo: _FakeCombo) -> None:
        self.combo = combo

    def descendants(self, control_type: str):
        if control_type == "ComboBox":
            return [self.combo]
        if control_type == "RadioButton":
            return []
        return []


def test_select_net_price_mode_uses_header_combo_when_radio_missing() -> None:
    combo = _FakeCombo("Gross")
    _select_net_price_mode(_FakeRoot(combo))
    assert combo.value == "Net"
