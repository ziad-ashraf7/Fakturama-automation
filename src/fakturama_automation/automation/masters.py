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
from fakturama_automation.automation.visual_debtor import select_debtor_row_visually
from fakturama_automation.config import Settings
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
    candidates = [
        window
        for window in app.desktop.windows()
        if window is not app.window
    ]
    candidates.extend(app.window.descendants(control_type="Window"))
    windows = [
        window
        for window in candidates
        if window.element_info.process_id == process_id
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
    edit = _named(root, name, ("Edit", "ComboBox"))
    edit.set_focus()
    keyboard.send_keys("^a")
    keyboard.send_keys(escape_keyboard_text(value), with_spaces=True)


def _labelled_edits(root: Any, label_name: str) -> list[Any]:
    labels = [
        label
        for label in root.descendants(control_type="Text")
        if _safe_name(label) == label_name and _visible(label)
    ]
    if len(labels) != 1:
        raise _automation_failure(
            f"Expected one visible {label_name!r} label, found {len(labels)}"
        )
    label = labels[0]
    label_rect = label.element_info.rectangle
    controls = [
        control
        for control in label.parent().descendants(control_type="Edit")
        if not _safe_name(control)
        and _visible(control)
        and control.element_info.rectangle.top < label_rect.bottom
        and control.element_info.rectangle.bottom > label_rect.top
        and control.element_info.rectangle.left >= label_rect.right
    ]
    controls.sort(key=lambda control: control.element_info.rectangle.left)
    return controls


def _editor_pane(app: FakturamaApp, tab_name: str) -> Any | None:
    tabs = [
        tab
        for tab in app.window.descendants(control_type="TabItem")
        if _safe_name(tab) == tab_name and _visible(tab)
    ]
    if len(tabs) != 1:
        return None
    panes = [
        child
        for child in tabs[0].parent().children(control_type="Pane")
        if _safe_name(child) == tab_name and _visible(child)
    ]
    return panes[0] if len(panes) == 1 else None


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


def _order_visible_text(root: Any) -> str:
    values: list[str] = []
    for control in [root, *root.descendants()]:
        for getter in (
            lambda control=control: _safe_name(control),
            lambda control=control: control.window_text(),
            lambda control=control: control.iface_value.CurrentValue,
        ):
            try:
                value = str(getter())
            except Exception:  # noqa: BLE001
                value = ""
            if value:
                values.append(value)
    return normalize_display(" ".join(values))


def _debtor_address_populated(order_view: OrderView, debtor: Debtor) -> bool:
    visible = _order_visible_text(order_view.root)
    expected = (
        debtor.company,
        debtor.billing_address.street,
        debtor.billing_address.zip_code,
        debtor.billing_address.city,
    )
    return all(normalize_display(value) in visible for value in expected if value)


def _select_debtor_row(
    dialog: Any,
    debtor: Debtor,
    settings: Settings,
    order_view: OrderView,
) -> bool:
    rows = [item for item in dialog.descendants(control_type="ListItem") if _visible(item)]
    expected_parts = tuple(
        part
        for part in (
            debtor.company,
            debtor.first_name,
            debtor.last_name,
            debtor.billing_address.zip_code,
            debtor.billing_address.city,
        )
        if part
    )
    matches = [
        row
        for row in rows
        if all(normalize_display(part) in normalize_display(_safe_name(row)) for part in expected_parts)
    ]
    if len(matches) > 1:
        raise MasterDataConflict("Multiple exact debtor rows", stage="debtor")
    if not matches:
        selected = select_debtor_row_visually(dialog, debtor, settings)
    else:
        row = matches[0]
        try:
            row.select()
        except (AttributeError, RuntimeError):
            row.click_input()
        selected = True
    if not selected:
        return False
    ok = _first_button(dialog, ("OK", "Select", "Use"))
    if ok is None:
        raise _automation_failure("Debtor selector has no confirmation button")
    ok.invoke()
    wait_until(
        "selected debtor address",
        lambda: True
        if not _visible(dialog) and _debtor_address_populated(order_view, debtor)
        else None,
        settings.uia_timeout_seconds,
    )
    return True


def _create_debtor(
    app: FakturamaApp,
    order_view: OrderView,
    debtor: Debtor,
    payment: Payment,
    settings: Settings,
) -> None:
    _open_data_item(app, "Debtors")
    new_button = wait_until(
        "new debtor action",
        lambda: _first_button(app.window, ("Create a new debtor",)),
        app.timeout,
    )
    new_button.invoke()
    editor = wait_until(
        "new debtor editor",
        lambda: _editor_pane(app, "New Debtor"),
        app.timeout,
    )
    _write(editor, "Company", debtor.company)
    name_fields = _labelled_edits(editor, "First Name Last Name")
    if debtor.first_name or debtor.last_name:
        if len(name_fields) != 2:
            raise _automation_failure("New debtor editor has no first/last name fields")
        if debtor.first_name:
            name_fields[0].set_focus()
            keyboard.send_keys(escape_keyboard_text(debtor.first_name), with_spaces=True)
        if debtor.last_name:
            name_fields[1].set_focus()
            keyboard.send_keys(escape_keyboard_text(debtor.last_name), with_spaces=True)

    address = debtor.billing_address
    _write(editor, "Street", address.street)
    zip_city = _labelled_edits(editor, "ZIP - City")
    if len(zip_city) != 2:
        raise _automation_failure("New debtor editor has no ZIP/City fields")
    zip_city[0].set_focus()
    keyboard.send_keys(escape_keyboard_text(address.zip_code), with_spaces=True)
    zip_city[1].set_focus()
    keyboard.send_keys(escape_keyboard_text(address.city), with_spaces=True)
    _write(editor, "Country", address.country)
    if address.email:
        _write(editor, "E-Mail", address.email)
    if address.telephone:
        _write(editor, "Telephone", address.telephone)

    misc_tab = [
        tab
        for tab in editor.descendants(control_type="TabItem")
        if _safe_name(tab) == "Miscellaneous" and _visible(tab)
    ]
    if len(misc_tab) != 1:
        raise _automation_failure("New debtor editor has no Miscellaneous tab")
    misc_tab[0].click_input()
    _write(editor, "Alias name", debtor.alias)
    _write(editor, "Payment", payment_code(payment.method))
    _write(editor, "Discount", "0")
    _write(editor, "Net or Gross", "Net")

    save_candidates = [
        button
        for button in app.window.descendants(control_type="Button")
        if _safe_name(button) == "Save the current contents"
        and _visible(button)
        and button.is_enabled()
    ]
    if len(save_candidates) != 1:
        raise _automation_failure(
            f"Expected one enabled debtor save action, found {len(save_candidates)}"
        )
    save_candidates[0].invoke()
    time.sleep(0.2)

    order_view.activate()
    order_view.find_section_image("Addresses").click_input()
    dialog = wait_until("debtor selector after creation", lambda: _dialog(app), app.timeout)
    search = [edit for edit in dialog.descendants(control_type="Edit") if _visible(edit)]
    if len(search) != 1:
        raise _automation_failure("Debtor selector did not return after creation")
    search[0].set_focus()
    keyboard.send_keys(escape_keyboard_text(debtor.company), with_spaces=True)
    if not _select_debtor_row(dialog, debtor, settings, order_view):
        raise _automation_failure("Created debtor was not selectable from the same Order")


def resolve_debtor(
    app: FakturamaApp,
    order_view: OrderView,
    debtor: Debtor,
    payment: Payment,
    settings: Settings,
) -> None:
    """Select one exact debtor, or create it while retaining the open Order."""

    order_view.find_section_image("Addresses").click_input()
    dialog = wait_until("debtor selector", lambda: _dialog(app), app.timeout)
    search = [edit for edit in dialog.descendants(control_type="Edit") if _visible(edit)]
    if len(search) != 1:
        raise _automation_failure(f"Expected one debtor search field, found {len(search)}")
    search[0].set_focus()
    keyboard.send_keys(escape_keyboard_text(debtor.company), with_spaces=True)
    if _select_debtor_row(dialog, debtor, settings, order_view):
        return

    _close_dialog(dialog)
    _create_debtor(app, order_view, debtor, payment, settings)


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
