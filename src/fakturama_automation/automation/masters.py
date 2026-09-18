"""Exact master-data resolution for the open Fakturama Order."""

from __future__ import annotations

import time
from collections.abc import Iterable
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
    wait_until,
)
from fakturama_automation.domain.models import Debtor, OrderItem, Payment
from fakturama_automation.domain.outcomes import MasterDataConflict
from fakturama_automation.domain.rules import (
    MatchDecision,
    classify_exact_match,
    payment_code,
    product_gross_price,
)


def normalize_display(value: str) -> str:
    return " ".join(value.split()).casefold()


def exact_decision(
    rows: list[dict[str, str]], expected: dict[str, str], fields: tuple[str, ...]
) -> MatchDecision:
    return classify_exact_match(rows, expected, fields)


def require_unambiguous(
    rows: list[dict[str, str]],
    expected: dict[str, str],
    fields: tuple[str, ...],
    *,
    stage: str,
) -> dict[str, str] | None:
    decision = exact_decision(rows, expected, fields)
    if decision is MatchDecision.MULTIPLE_MATCHES:
        raise MasterDataConflict("Multiple exact master-data matches", stage=stage)
    if decision is MatchDecision.NO_MATCH:
        return None
    return next(
        row
        for row in rows
        if all(
            normalize_display(row.get(field, ""))
            == normalize_display(expected.get(field, ""))
            for field in fields
        )
    )


def _dialog(app: FakturamaApp, title: str | None = None):
    process_id = app.window.element_info.process_id
    windows = [
        window
        for window in app.desktop.windows()
        if window.element_info.process_id == process_id
        and window is not app.window
        and _visible(window)
        and (title is None or _safe_name(window) == title or window.window_text() == title)
    ]
    if not windows:
        return None
    return windows[-1]


def _named(root: Any, name: str, control_types: tuple[str, ...] = ("Edit",)):
    found = [
        control
        for control_type in control_types
        for control in root.descendants(control_type=control_type)
        if _safe_name(control) == name and _visible(control)
    ]
    if len(found) != 1:
        raise _automation_failure(f"Expected one {name!r} control, found {len(found)}")
    return found[0]


def _write(root: Any, name: str, value: str) -> None:
    edit = _named(root, name)
    edit.set_focus()
    keyboard.send_keys("^a")
    keyboard.send_keys(escape_keyboard_text(value), with_spaces=True)


def _first_button(root: Any, names: Iterable[str]):
    for name in names:
        matches = [
            button
            for button in root.descendants(control_type="Button")
            if _safe_name(button) == name and _visible(button)
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _select_single_row(dialog: Any, expected_parts: tuple[str, ...], stage: str) -> bool:
    rows = [item for item in dialog.descendants(control_type="ListItem") if _visible(item)]
    matches = [
        row
        for row in rows
        if all(normalize_display(part) in normalize_display(_safe_name(row)) for part in expected_parts)
    ]
    if len(matches) > 1:
        raise MasterDataConflict(f"Multiple exact {stage} matches", stage=stage)
    if not matches:
        return False
    row = matches[0]
    try:
        row.select()
    except (AttributeError, RuntimeError):
        row.click_input()
    ok = _first_button(dialog, ("OK", "Select", "Use"))
    if ok is None:
        raise _automation_failure(f"{stage} dialog has no confirmation button")
    ok.invoke()
    return True


def resolve_debtor(app: FakturamaApp, order_view: OrderView, debtor: Debtor, payment: Payment) -> None:
    """Select one exact debtor, or create it through the visible contact dialog."""

    order_view.find_section_image("Addresses").click_input()
    dialog = wait_until("debtor selector", lambda: _dialog(app), app.timeout)
    search = [edit for edit in dialog.descendants(control_type="Edit") if _visible(edit)]
    if len(search) != 1:
        raise _automation_failure(f"Expected one debtor search field, found {len(search)}")
    search[0].set_focus()
    keyboard.send_keys(escape_keyboard_text(debtor.company), with_spaces=True)
    expected_parts = tuple(
        part
        for part in (
            debtor.company,
            debtor.alias,
            debtor.billing_address.zip_code,
            debtor.billing_address.city,
        )
        if part
    )
    if _select_single_row(dialog, expected_parts, "debtor"):
        return

    new_button = _first_button(dialog, ("New Contact", "Create a new contact", "New"))
    if new_button is None:
        raise _automation_failure("No exact debtor and no contact-creation action available")
    new_button.invoke()
    editor = wait_until("new debtor editor", lambda: _dialog(app), app.timeout)
    _write(editor, "Company", debtor.company)
    if debtor.first_name:
        _write(editor, "First name", debtor.first_name)
    if debtor.last_name:
        _write(editor, "Last name", debtor.last_name)
    _write(editor, "Alias", debtor.alias)
    address = debtor.billing_address
    _write(editor, "Street", address.street)
    _write(editor, "ZIP", address.zip_code)
    _write(editor, "City", address.city)
    _write(editor, "Country", address.country)
    if address.email:
        _write(editor, "Email", address.email)
    if address.telephone:
        _write(editor, "Telephone", address.telephone)
    _write(editor, "Payment method", payment_code(payment.method))
    save = _first_button(editor, ("Save the current contents", "OK", "Save"))
    if save is None:
        raise _automation_failure("New debtor editor has no save action")
    save.invoke()
    time.sleep(0.1)
    dialog = wait_until("debtor selector after creation", lambda: _dialog(app), app.timeout)
    search = [edit for edit in dialog.descendants(control_type="Edit") if _visible(edit)]
    if len(search) != 1:
        raise _automation_failure("Debtor selector did not return after creation")
    search[0].set_focus()
    keyboard.send_keys(escape_keyboard_text(debtor.company), with_spaces=True)
    if not _select_single_row(dialog, expected_parts, "debtor"):
        raise _automation_failure("Created debtor was not selectable from the same Order")


def ensure_payment_method(app: FakturamaApp | None, payment_method: str) -> str:
    """Return the assignment-required Fakturama payment code."""

    del app
    return payment_code(payment_method)



def _open_data_item(app: FakturamaApp, name: str) -> Any:
    data_items = [
        item
        for item in app.window.descendants(control_type="MenuItem")
        if _safe_name(item) == "Data" and _visible(item)
    ]
    if len(data_items) != 1:
        raise _automation_failure("Data menu is not uniquely available")
    data_items[0].invoke()
    item = wait_until(
        f"Data menu item {name}",
        lambda: next(
            (
                candidate
                for candidate in app.window.descendants(control_type="MenuItem")
                if _safe_name(candidate) == name and _visible(candidate)
            ),
            None,
        ),
        app.timeout,
    )
    item.invoke()
    return item


def _close_dialog(dialog: Any) -> None:
    close = _first_button(dialog, ("Close", "Cancel"))
    if close is not None:
        close.invoke()
        return
    try:
        dialog.close()
    except (AttributeError, RuntimeError):
        keyboard.send_keys("{ESC}")


def ensure_vat(app: FakturamaApp, order_view: OrderView, vat_percent: Decimal) -> str:
    """Ensure the exact VAT definition is available and return its expected name."""

    del order_view
    expected = f"VAT {vat_percent.normalize()}%"
    _open_data_item(app, "VATs")
    dialog = wait_until("VAT maintenance dialog", lambda: _dialog(app), app.timeout)
    names = [
        _safe_name(item)
        for item in dialog.descendants(control_type="ListItem")
        if _visible(item)
    ]
    exact = [name for name in names if normalize_display(name) == normalize_display(expected)]
    if len(exact) > 1:
        raise MasterDataConflict(f"Multiple VAT rows named {expected}", stage="vat")
    if not exact:
        new_button = _first_button(dialog, ("New", "Create"))
        if new_button is None:
            raise _automation_failure(f"Missing VAT {expected} and no create action")
        new_button.invoke()
        editor = wait_until("new VAT editor", lambda: _dialog(app), app.timeout)
        _write(editor, "Name", expected)
        _write(editor, "Value", str(vat_percent))
        _write(editor, "E-Invoice VAT code", "S")
        save = _first_button(editor, ("Save", "OK"))
        if save is None:
            raise _automation_failure("VAT editor has no save action")
        save.invoke()
        dialog = wait_until("VAT maintenance after creation", lambda: _dialog(app), app.timeout)
    _close_dialog(dialog)
    return expected


def _create_product(app: FakturamaApp, item: OrderItem, vat_name: str) -> None:
    _open_data_item(app, "Products")
    dialog = wait_until("Product maintenance dialog", lambda: _dialog(app), app.timeout)
    new_button = _first_button(dialog, ("New", "Create"))
    if new_button is None:
        raise _automation_failure("Product maintenance has no create action")
    new_button.invoke()
    editor = wait_until("new Product editor", lambda: _dialog(app), app.timeout)
    _write(editor, "Item Number", item.sku)
    _write(editor, "Name", item.description)
    _write(editor, "Cost", "0")
    _write(editor, "Stock", "0")
    _write(editor, "Price", str(product_gross_price(item.unit_net, item.vat_percent)))
    vat_controls = [
        control
        for control_type in ("Edit", "ComboBox")
        for control in editor.descendants(control_type=control_type)
        if _safe_name(control) == "VAT" and _visible(control)
    ]
    if len(vat_controls) == 1:
        vat_controls[0].set_focus()
        keyboard.send_keys(escape_keyboard_text(vat_name), with_spaces=True)
    save = _first_button(editor, ("Save", "OK"))
    if save is None:
        raise _automation_failure("Product editor has no save action")
    save.invoke()
    dialog = wait_until("Product maintenance after creation", lambda: _dialog(app), app.timeout)
    _close_dialog(dialog)


def resolve_product(app: FakturamaApp, order_view: OrderView, item: OrderItem) -> None:
    """Resolve an exact SKU, creating the master record when no match exists."""

    try:
        order_view.insert_unique_product(item.sku)
        return
    except Exception as error:  # noqa: BLE001
        picker = app._picker()
        if picker is not None:
            cancel = _first_button(picker, ("Cancel", "Close"))
            if cancel is not None:
                cancel.invoke()
            else:
                keyboard.send_keys("{ESC}")
        try:
            vat_name = ensure_vat(app, order_view, item.vat_percent)
            _create_product(app, item, vat_name)
            order_view.insert_unique_product(item.sku)
        except Exception:  # noqa: BLE001
            raise error
