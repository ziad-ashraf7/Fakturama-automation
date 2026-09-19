from decimal import Decimal
from types import SimpleNamespace

import pytest

from fakturama_automation.automation import documents
from fakturama_automation.automation.documents import (
    _find_invoice_documents_row,
    _invoke_named,
    _select_invoice_payment_method,
    _select_net_price_mode,
)
from fakturama_automation.domain.outcomes import AutomationFailure


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


class _FakePaidCheckBox:
    def __init__(self) -> None:
        self.element_info = SimpleNamespace(
            name="paid",
            control_type="CheckBox",
            class_name="CheckBox",
            rectangle=SimpleNamespace(top=100, bottom=120),
        )

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True


class _FakeOpenButton:
    def __init__(self, combo: "_FakePaymentCombo") -> None:
        self.combo = combo
        self.element_info = SimpleNamespace(
            name="Open",
            control_type="Button",
            class_name="Button",
        )

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def invoke(self) -> None:
        self.combo.opened = True


class _FakePaymentItem:
    def __init__(self, combo: "_FakePaymentCombo") -> None:
        self.combo = combo
        self.element_info = SimpleNamespace(
            name="Credit transfer",
            control_type="ListItem",
            class_name="ListItem",
        )

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def is_selected(self) -> bool:
        return self.combo.value == "Credit transfer"

    def click_input(self) -> None:
        self.combo.value = "Credit transfer"


class _FakePaymentCombo(_FakeCombo):
    def __init__(self) -> None:
        super().__init__("Pay Cash")
        self.opened = False
        self.element_info.rectangle = SimpleNamespace(top=100, bottom=120)
        self.open_button = _FakeOpenButton(self)
        self.item = _FakePaymentItem(self)

    def descendants(self, control_type: str):
        if control_type == "Button":
            return [self.open_button]
        return []

    def select(self, value: str) -> None:
        raise AssertionError(f"direct combo select should not be used for {value!r}")


class _FakeInvoiceRoot:
    def __init__(self) -> None:
        self.paid = _FakePaidCheckBox()
        self.payment_combo = _FakePaymentCombo()

    def descendants(self, control_type: str):
        if control_type == "CheckBox":
            return [self.paid]
        if control_type == "ComboBox":
            return [self.payment_combo]
        if control_type == "ListItem" and self.payment_combo.opened:
            return [self.payment_combo.item]
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


def _invoice_row(
    number: str = "INV000001",
    reference: str = "WEB-2026-0714-A17",
    total: str = "$678.30",
    state: str = "paid",
) -> dict[str, str]:
    return {
        "Document": number,
        "Cust.Ref.": reference,
        "Total": total,
        "State": state,
    }


def test_persisted_invoice_requires_generated_number_and_matching_documents_row() -> None:
    result = documents.verify_persisted_invoice(
        number="INV000001",
        external_reference="WEB-2026-0714-A17",
        total=Decimal("678.30"),
        state="paid",
        document_row=_invoice_row(),
    )

    assert result.number == "INV000001"
    assert result.total == Decimal("678.30")
    assert result.state == "paid"


def test_persisted_invoice_rejects_new_placeholder_after_save() -> None:
    with pytest.raises(AutomationFailure, match="Generated Invoice number"):
        documents.verify_persisted_invoice(
            number="new",
            external_reference="WEB-2026-0714-A17",
            total=Decimal("678.30"),
            state="paid",
            document_row=_invoice_row(number="new"),
        )


def test_persisted_invoice_rejects_missing_documents_row() -> None:
    with pytest.raises(AutomationFailure, match="Documents row"):
        documents.verify_persisted_invoice(
            number="INV000001",
            external_reference="WEB-2026-0714-A17",
            total=Decimal("678.30"),
            state="paid",
            document_row=None,
        )


def test_persisted_invoice_rejects_wrong_reference_or_total() -> None:
    with pytest.raises(AutomationFailure, match="Cust.Ref."):
        documents.verify_persisted_invoice(
            number="INV000001",
            external_reference="WEB-2026-0714-A17",
            total=Decimal("678.30"),
            state="paid",
            document_row=_invoice_row(reference="WRONG"),
        )

    with pytest.raises(AutomationFailure, match="Total"):
        documents.verify_persisted_invoice(
            number="INV000001",
            external_reference="WEB-2026-0714-A17",
            total=Decimal("678.30"),
            state="paid",
            document_row=_invoice_row(total="$1.00"),
        )


class _FakeCategoryRoot:
    def __init__(self, name: str) -> None:
        self.name = name
        self.selected = False

    def select(self) -> None:
        self.selected = True


def test_invoice_documents_search_checks_each_native_category() -> None:
    orders = _FakeCategoryRoot("orders")
    invoices = _FakeCategoryRoot("invoices")

    def rows_for(root: _FakeCategoryRoot) -> tuple[dict[str, str], ...]:
        if root is orders:
            return (_invoice_row(number="PO000001"),)
        return (_invoice_row(),)

    row = _find_invoice_documents_row(
        (orders, invoices), rows_for, invoice_number="INV000001"
    )

    assert row["Document"] == "INV000001"
    assert orders.selected is True
    assert invoices.selected is True


def test_invoice_documents_search_fails_when_no_category_contains_invoice() -> None:
    categories = (_FakeCategoryRoot("orders"), _FakeCategoryRoot("invoices"))

    with pytest.raises(AutomationFailure, match="not found in any document category"):
        _find_invoice_documents_row(
            categories,
            lambda _root: (_invoice_row(number="PO000001"),),
            invoice_number="INV000001",
        )
