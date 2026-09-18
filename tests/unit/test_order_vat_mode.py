from types import SimpleNamespace

from fakturama_automation.automation.documents import _select_vat_mode


class _FakeVatCombo:
    def __init__(self, value: str) -> None:
        self.value = value
        self.element_info = SimpleNamespace(
            name="VAT",
            control_type="ComboBox",
            class_name="ComboBox",
        )

    @property
    def iface_value(self):
        return SimpleNamespace(CurrentValue=self.value)

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def select(self, value: str) -> None:
        self.value = value


class _FakeRoot:
    def __init__(self, combo: _FakeVatCombo) -> None:
        self.combo = combo

    def descendants(self, control_type: str):
        if control_type == "ComboBox":
            return [self.combo]
        return []


def test_select_vat_mode_uses_named_combobox_and_readback() -> None:
    combo = _FakeVatCombo("Gross")

    _select_vat_mode(_FakeRoot(combo))

    assert combo.value == "With VAT"
