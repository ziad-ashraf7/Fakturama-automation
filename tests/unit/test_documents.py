from types import SimpleNamespace

from fakturama_automation.automation.documents import (
    _invoke_named,
    _select_invoice_payment_method,
    _select_net_price_mode,
)


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


class _FakeValueEdit:
    def __init__(self) -> None:
        self.element_info = SimpleNamespace(
            name="Value",
            control_type="Edit",
            class_name="Edit",
            rectangle=SimpleNamespace(top=100, bottom=120),
        )

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True


class _FakePaymentCombo(_FakeCombo):
    def __init__(self) -> None:
        super().__init__("Pay Cash")
        self.element_info.rectangle = SimpleNamespace(top=100, bottom=120)


class _FakeInvoiceRoot:
    def __init__(self) -> None:
        self.value_edit = _FakeValueEdit()
        self.payment_combo = _FakePaymentCombo()

    def descendants(self, control_type: str):
        if control_type == "Edit":
            return [self.value_edit]
        if control_type == "ComboBox":
            return [self.payment_combo]
        return []


def test_select_invoice_payment_method_uses_mapped_combo_and_readback() -> None:
    root = _FakeInvoiceRoot()

    _select_invoice_payment_method(root, "Credit transfer")

    assert root.payment_combo.value == "Credit transfer"


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
