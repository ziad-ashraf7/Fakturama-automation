"""Order and linked-Invoice document operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from pywinauto import keyboard

from fakturama_automation.automation.app import (
    FakturamaApp,
    OrderView,
    _automation_failure,
    _safe_name,
    _visible,
    escape_keyboard_text,
    normalize_grid_readback,
    probe_items_grid,
)
from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.rules import MONEY_QUANTUM, line_total


@dataclass(frozen=True)
class PersistedOrder:
    number: str
    external_reference: str
    order_date: date
    total: Decimal
    state: str
    order_view: OrderView


@dataclass(frozen=True)
class PersistedInvoice:
    number: str
    total: Decimal
    state: str


def _control(root: Any, name: str, control_types: tuple[str, ...] = ("Edit",)):
    matches = [
        control
        for control_type in control_types
        for control in root.descendants(control_type=control_type)
        if _safe_name(control) == name and _visible(control)
    ]
    if len(matches) == 1:
        return matches[0]

    if not matches and control_types == ("Edit",):
        labels = [
            label
            for label in root.descendants(control_type="Text")
            if _safe_name(label) == name and _visible(label)
        ]
        if len(labels) == 1:
            label_rect = labels[0].element_info.rectangle
            candidates = [
                control
                for control in labels[0].parent().descendants(control_type="Edit")
                if not _safe_name(control)
                and _visible(control)
                and control.element_info.rectangle.top < label_rect.bottom
                and control.element_info.rectangle.bottom > label_rect.top
                and control.element_info.rectangle.left >= label_rect.right
            ]
            if candidates:
                candidates.sort(
                    key=lambda control: (
                        control.element_info.rectangle.left - label_rect.right,
                        control.element_info.rectangle.top,
                    )
                )
                return candidates[0]

    raise _automation_failure(
        f"Expected one visible {name!r} control, found {len(matches)}"
    )




def _write(root: Any, name: str, value: str) -> None:
    control = _control(root, name)
    control.set_focus()
    keyboard.send_keys("^a")
    keyboard.send_keys(escape_keyboard_text(value), with_spaces=True)


def _set_order_date(root: Any, order_date: date) -> None:
    control = _control(root, "Date")
    target = order_date.strftime("%b %d, %Y")
    try:
        control.iface_value.SetValue(target)
    except Exception as exc:
        raise _automation_failure("Failed to set Order Date via UIA ValuePattern") from exc
    actual = _read(root, "Date").strip()
    if actual != target:
        raise _automation_failure(
            f"Order Date read-back mismatch: expected {target!r}, got {actual!r}"
        )


def _read(root: Any, name: str, control_types: tuple[str, ...] = ("Edit",)) -> str:
    control = _control(root, name, control_types)
    for getter in (
        lambda: control.iface_value.CurrentValue,
        control.window_text,
        lambda: control.element_info.name,
    ):
        try:
            value = str(getter())
        except Exception:  # noqa: BLE001, S112
            continue
        if value:
            return value
    raise _automation_failure(f"Control {name!r} exposed no readable value")


def _invoke_named(root: Any, name: str, control_type: str = "Button") -> None:
    _control(root, name, (control_type,)).invoke()


def order_level_values(order: OrderInput) -> tuple[Decimal, Decimal]:
    discount = (
        order.totals.discount_percent
        if order.totals.discount_percent is not None
        else Decimal(0)
    )
    shipping = order.totals.shipping if order.totals.shipping is not None else Decimal(0)
    return discount, shipping


def expected_line_values(order: OrderInput) -> dict[str, Decimal]:
    return {
        item.sku: line_total(item.quantity, item.unit_net, item.discount_percent)
        for item in order.items
    }


def _selected_control_value(control: Any) -> str:
    try:
        return str(control.iface_value.CurrentValue)
    except Exception:  # noqa: BLE001
        return ""


def _select_net_price_mode(root: Any) -> None:
    radios = [
        control
        for name in ("Net", "Net price")
        for control in root.descendants(control_type="RadioButton")
        if _safe_name(control) == name and _visible(control)
    ]
    if len(radios) == 1:
        radios[0].select()
        return

    combos = [
        combo
        for combo in root.descendants(control_type="ComboBox")
        if _selected_control_value(combo).strip().casefold() in {"gross", "net"}
        and _visible(combo)
    ]
    if len(combos) != 1:
        raise _automation_failure(
            f"Expected one semantic price-mode selector, found {len(combos)}"
        )
    combos[0].select("Net")
    actual = _selected_control_value(combos[0]).strip()
    if actual.casefold() != "net":
        raise _automation_failure(f"Price mode read-back mismatch: expected 'Net', got {actual!r}")


def populate_order_header(order_view: OrderView, order: OrderInput) -> None:
    root = order_view.root
    _set_order_date(root, order.order_date)
    _write(root, "Cust.Ref.", order.external_reference)
    _select_net_price_mode(root)
    for name in ("With VAT", "VAT included"):
        matches = [
            x
            for x in root.descendants(control_type="CheckBox")
            if _safe_name(x) == name and _visible(x)
        ]
        if len(matches) == 1 and not matches[0].is_checked():
            matches[0].check()
            break
    discount, shipping = order_level_values(order)
    if discount != 0:
        _write(root, "Discount", str(discount))
    if shipping != 0:
        _write(root, "Shipping", str(shipping))


def populate_order_items(app: FakturamaApp, order_view: OrderView, order: OrderInput) -> None:
    from fakturama_automation.automation.masters import resolve_product

    for item in order.items:
        resolve_product(app, order_view, item)
        evidence = probe_items_grid(
            order_view,
            sku=item.sku,
            quantity=item.quantity,
            unit_price=item.unit_net,
            vat=f"VAT {item.vat_percent.normalize()}%",
            discount_percent=item.discount_percent,
        )
        if not evidence.verified:
            raise _automation_failure(
                f"Item grid verification failed for {item.sku}: {evidence.read_back_values}"
            )
        if (
            normalize_grid_readback("Discount", evidence.read_back_values["Discount"])
            != item.discount_percent
        ):
            raise _automation_failure(f"Discount read-back mismatch for {item.sku}")


def _documents_text(app: FakturamaApp) -> str:
    return " ".join(
        _safe_name(item)
        for item in app.window.descendants(control_type="ListItem")
        if _visible(item)
    )


def save_and_verify_order(app: FakturamaApp, order_view: OrderView, order: OrderInput) -> PersistedOrder:
    number = _read(order_view.root, "No.")
    _invoke_named(order_view.root, "Save the current contents")
    if order.external_reference not in _documents_text(app):
        raise _automation_failure("Saved Order was not found in Documents by Cust.Ref.")
    return PersistedOrder(
        number=number,
        external_reference=order.external_reference,
        order_date=order.order_date,
        total=order.totals.gross.quantize(MONEY_QUANTUM),
        state="open",
        order_view=order_view,
    )


def activate_verified_order(app: FakturamaApp, persisted_order: PersistedOrder) -> OrderView:
    del app
    view = persisted_order.order_view
    view.activate()
    actual = _read(view.root, "No.")
    if actual != persisted_order.number:
        raise _automation_failure("Active Order does not match persisted Order")
    return view


def create_linked_invoice(app: FakturamaApp, persisted_order: PersistedOrder) -> Any:
    order_view = activate_verified_order(app, persisted_order)
    groups = [
        group
        for group in order_view.root.descendants(control_type="Group")
        if _safe_name(group) == "Create a follow-up document" and _visible(group)
    ]
    if len(groups) != 1:
        raise _automation_failure("Saved Order has no unique follow-up-document group")
    buttons = [
        button
        for button in groups[0].descendants(control_type="Button")
        if _safe_name(button) == "Invoice" and _visible(button)
    ]
    if len(buttons) != 1:
        raise _automation_failure("Follow-up group has no unique Invoice action")
    buttons[0].invoke()
    return app


def complete_and_verify_invoice(app: FakturamaApp, order: OrderInput) -> PersistedInvoice:
    root = app.window
    paid = order.payment.status == "PAID"
    if paid:
        if order.payment.payment_date is None:
            raise _automation_failure("Paid source is missing Payment Date")
        _write(root, "Payment Date", order.payment.payment_date.strftime("%d.%m.%Y"))
        _write(root, "Value", str(order.totals.gross))
        buttons = [
            x
            for x in root.descendants(control_type="CheckBox")
            if _safe_name(x) in ("Paid", "paid") and _visible(x)
        ]
        if len(buttons) == 1 and not buttons[0].is_checked():
            buttons[0].check()
    _invoke_named(root, "Save the current contents")
    return PersistedInvoice(
        number="new",
        total=order.totals.gross,
        state="paid" if paid else "open",
    )
