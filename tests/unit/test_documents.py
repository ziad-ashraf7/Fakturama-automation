from types import SimpleNamespace

from fakturama_automation.automation.documents import _invoke_named, _select_net_price_mode


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


class _FakeButton:
    def __init__(self) -> None:
        self.element_info = SimpleNamespace(
            name="Save the current contents",
            control_type="Button",
            class_name="",
        )
        self.invoked = False

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def invoke(self) -> None:
        self.invoked = True


class _FakeApplicationWindow:
    def __init__(self, button: _FakeButton) -> None:
        self.button = button

    def descendants(self, control_type: str):
        return [self.button] if control_type == "Button" else []


def test_save_action_is_resolved_from_application_window_scope() -> None:
    button = _FakeButton()
    _invoke_named(_FakeApplicationWindow(button), "Save the current contents")
    assert button.invoked


def test_normalize_payment_value() -> None:
    from decimal import Decimal

    from fakturama_automation.automation.app import normalize_grid_readback

    assert normalize_grid_readback("Value", "$678.30") == Decimal("678.30")
