"""Exact master-data resolution for the open Fakturama Order."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
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


def _select_combo_value(root: Any, name: str, value: str) -> None:
    combo = _named(root, name, ('ComboBox',))
    opens = [button for button in combo.descendants(control_type='Button') if _safe_name(button) == 'Open' and _visible(button)]
    if len(opens) != 1:
        raise _automation_failure(f'ComboBox {name!r} has no unique Open action')
    opens[0].invoke()
    item = wait_until(
        f'combo value {value!r}',
        lambda: next((candidate for candidate in root.parent().descendants(control_type='ListItem') if _safe_name(candidate) == value and _visible(candidate)), None),
        5.0,
    )
    item.click_input()


def _set_formatted_percent(root: Any, name: str, value: Decimal) -> None:
    edit = _named(root, name, ('Edit',))
    edit.click_input()
    keyboard.send_keys('{HOME}')
    keyboard.send_keys('+{END}')
    rendered = format(value, 'f').rstrip('0').rstrip('.') or '0'
    keyboard.send_keys(rendered)
    keyboard.send_keys('{TAB}')
    try:
        actual = str(edit.iface_value.CurrentValue).replace(' ', '')
    except Exception as error:
        raise _automation_failure(f'Could not read formatted {name!r} value') from error
    if actual not in {rendered, f'{rendered}%'}:
        raise _automation_failure(
            f'Formatted {name!r} value mismatch: expected {rendered!r}, got {actual!r}'
        )


def _editor_pane(app: FakturamaApp, tab_name: str) -> Any | None:
    tabs = [
        tab
        for tab in app.window.descendants(control_type="TabItem")
        if _safe_name(tab) == tab_name and _visible(tab)
    ]
    if not tabs:
        return None
    tabs[0].click_input()
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


_DELIVERY_ADDRESS_TYPE = "Delivery address"


def debtor_addresses_complete(visible_text: str, debtor: Debtor) -> bool:
    """Check billing and, when supplied, delivery address role values."""

    normalized = normalize_display(visible_text)
    billing_values = (
        debtor.company,
        debtor.billing_address.street,
        debtor.billing_address.zip_code,
        debtor.billing_address.city,
        debtor.billing_address.country,
    )
    if any(normalize_display(value) not in normalized for value in billing_values if value):
        return False
    delivery = debtor.delivery_address
    if delivery is None:
        return True
    delivery_values = (
        delivery.additional_name,
        delivery.street,
        delivery.zip_code,
        delivery.city,
        delivery.country,
        _DELIVERY_ADDRESS_TYPE,
    )
    return all(normalize_display(value) in normalized for value in delivery_values if value)


def _address_tabs(editor: Any) -> list[Any]:
    return [
        tab
        for tab in editor.descendants(control_type="TabItem")
        if _visible(tab)
        and (
            _safe_name(tab) == "Main address"
            or normalize_display(_safe_name(tab)).startswith("additional address #")
        )
    ]


def _address_tab(editor: Any, name: str) -> Any | None:
    return next((tab for tab in _address_tabs(editor) if _safe_name(tab) == name), None)


def _address_content_pane(tab: Any) -> Any:
    panes = [
        child
        for child in tab.parent().children(control_type="Pane")
        if _visible(child)
    ]
    if len(panes) != 1:
        raise _automation_failure(
            f"Expected one content Pane for address tab {_safe_name(tab)!r}, found {len(panes)}"
        )
    return panes[0]


def _write_labelled_edit(root: Any, label_name: str, value: str) -> None:
    fields = _labelled_edits(root, label_name)
    if len(fields) != 1:
        raise _automation_failure(
            f"Expected one editable field for {label_name!r}, found {len(fields)}"
        )
    fields[0].set_focus()
    keyboard.send_keys("^a")
    keyboard.send_keys(escape_keyboard_text(value), with_spaces=True)


def _delivery_address_visible(address_pane: Any, debtor: Debtor) -> bool:
    delivery = debtor.delivery_address
    if delivery is None:
        return True
    visible = _order_visible_text(address_pane)
    expected = (
        delivery.additional_name,
        delivery.street,
        delivery.zip_code,
        delivery.city,
        delivery.country,
        _DELIVERY_ADDRESS_TYPE,
    )
    return all(normalize_display(value) in visible for value in expected if value)


def ensure_delivery_address(editor: Any, debtor: Debtor, timeout: float) -> None:
    """Create or reuse the source delivery address in an open debtor editor."""

    delivery = debtor.delivery_address
    if delivery is None:
        return
    addresses_tab = next(
        (
            tab
            for tab in editor.descendants(control_type="TabItem")
            if _safe_name(tab) == "Addresses" and _visible(tab)
        ),
        None,
    )
    if addresses_tab is None:
        raise _automation_failure("Debtor editor has no Addresses tab")
    addresses_tab.click_input()

    delivery_tab = None
    for tab in _address_tabs(editor):
        tab.click_input()
        pane = _address_content_pane(tab)
        if _delivery_address_visible(pane, debtor):
            delivery_tab = tab
            break
        if delivery_tab is None and normalize_display(_safe_name(tab)).startswith(
            "additional address #"
        ):
            delivery_tab = tab

    if delivery_tab is None:
        plus_buttons = [
            button
            for button in addresses_tab.parent().descendants(control_type="Button")
            if _safe_name(button) == "+" and _visible(button)
        ]
        if len(plus_buttons) != 1:
            raise _automation_failure(
                f"Expected one additional-address action, found {len(plus_buttons)}"
            )
        plus_buttons[0].invoke()
        delivery_tab = wait_until(
            "additional debtor address",
            lambda: next(
                (
                    tab
                    for tab in _address_tabs(editor)
                    if normalize_display(_safe_name(tab)).startswith("additional address #")
                    and _visible(tab)
                ),
                None,
            ),
            timeout,
        )

    delivery_tab.click_input()
    delivery_pane = _address_content_pane(delivery_tab)
    if not _delivery_address_visible(delivery_pane, debtor):
        if delivery.additional_name:
            _write(delivery_pane, "additional name", delivery.additional_name)
        _write(delivery_pane, "Street", delivery.street)
        zip_city = _labelled_edits(delivery_pane, "ZIP - City")
        if len(zip_city) != 2:
            raise _automation_failure("Delivery address has no ZIP/City fields")
        zip_city[0].set_focus()
        keyboard.send_keys("^a")
        keyboard.send_keys(escape_keyboard_text(delivery.zip_code), with_spaces=True)
        zip_city[1].set_focus()
        keyboard.send_keys("^a")
        keyboard.send_keys(escape_keyboard_text(delivery.city), with_spaces=True)
        _write(delivery_pane, "Country", delivery.country)
        _write_labelled_edit(delivery_pane, "address type", _DELIVERY_ADDRESS_TYPE)
        keyboard.send_keys("{TAB}")

    main_tab = _address_tab(editor, "Main address")
    if main_tab is None:
        raise _automation_failure("Debtor editor has no Main address tab")
    main_tab.click_input()
    main_pane = _address_content_pane(main_tab)
    main_text = _order_visible_text(main_pane)
    delivery_tab.click_input()
    delivery_pane = _address_content_pane(delivery_tab)
    delivery_text = _order_visible_text(delivery_pane)
    editor_text = _order_visible_text(editor)
    if not debtor_addresses_complete(f"{editor_text} {main_text} {delivery_text}", debtor):
        raise _automation_failure("Debtor billing/delivery address read-back failed")


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
    ensure_delivery_address(editor, debtor, settings.uia_timeout_seconds)

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


def payment_term_decision(names: Sequence[str], expected: str) -> str:
    matches = [name for name in names if normalize_display(name) == normalize_display(expected)]
    if len(matches) > 1:
        raise MasterDataConflict(
            f"Multiple payment terms named {expected}", stage="payment_method"
        )
    return "reuse" if matches else "create"


def _payment_term_table(markdown: str) -> tuple[tuple[str, ...] | None, tuple[tuple[str, ...], ...]]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(normalize_display(cell) == "name" for cell in _markdown_cells(line))
        ),
        None,
    )
    separator_index = next(
        (
            index
            for index, line in enumerate(lines)
            if _is_markdown_separator(_markdown_cells(line))
        ),
        None,
    )
    data_start = (
        separator_index + 1
        if separator_index is not None
        else header_index + 1
        if header_index is not None
        else 0
    )
    rows: list[tuple[str, ...]] = []
    for line in lines[data_start:]:
        cells = _markdown_cells(line)
        if not cells or _is_markdown_separator(cells):
            continue
        rows.append(tuple(cells))
    headers = (
        tuple(_markdown_cells(lines[header_index])) if header_index is not None else None
    )
    return headers, tuple(rows)


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(
        cell.replace("-", "").replace(":", "").strip() == "" for cell in cells
    )


def payment_term_lookup_decision(markdown: str, expected: str) -> str:
    headers, rows = _payment_term_table(markdown)
    if headers is not None:
        name_columns = [
            index
            for index, cell in enumerate(headers)
            if normalize_display(cell) == "name"
        ]
        if name_columns:
            name_column = name_columns[0]
            names = tuple(
                row[name_column].strip()
                for row in rows
                if name_column < len(row) and row[name_column].strip()
            )
            return payment_term_decision(names, expected)

    expected_normalized = normalize_display(expected)
    matching_rows = [
        row
        for row in rows
        if any(normalize_display(cell) == expected_normalized for cell in row)
    ]
    if len(matching_rows) > 1:
        raise MasterDataConflict(
            f"Multiple visible payment terms named {expected}", stage="payment_method"
        )
    if matching_rows:
        return "reuse"
    if not rows:
        return "create"
    raise _automation_failure(
        f"Visible payment-term rows did not contain exact {expected!r}"
    )


def _payment_terms_pane(app: FakturamaApp) -> Any:
    tab = app.find_unique("terms of payment", "TabItem")
    tab.click_input()
    panes = [
        pane
        for pane in tab.parent().children(control_type="Pane")
        if _safe_name(pane) == "terms of payment" and _visible(pane)
    ]
    if len(panes) != 1:
        raise _automation_failure("Terms-of-payment view has no unique content Pane")
    return panes[0]


def _visible_payment_term_decision(app: FakturamaApp, pane: Any, expected: str) -> str:
    settings = app.settings
    if settings is None or settings.mistral_api_key is None:
        raise _automation_failure("MISTRAL_API_KEY is required for payment-term OCR")
    search = _labelled_edits(pane, "Search:")
    if len(search) != 1:
        raise _automation_failure("Terms-of-payment view has no unique Search field")
    from fakturama_automation.automation.visual_items import _ocr_markdown

    return payment_term_lookup_decision(
        _ocr_markdown(pane.capture_as_image(), settings), expected
    )


def _select_payment_code(editor: Any, expected: str) -> None:
    combo = _named(editor, "!editorPaymentPaymentcode!", ("ComboBox",))
    opens = [
        button
        for button in combo.descendants(control_type="Button")
        if _safe_name(button) == "Open" and _visible(button)
    ]
    if len(opens) != 1:
        raise _automation_failure("Payment-term code selector has no unique Open action")
    opens[0].invoke()
    item = wait_until(
        f"payment-term code {expected!r}",
        lambda: next(
            (
                candidate
                for candidate in editor.parent().descendants(control_type="ListItem")
                if normalize_display(_safe_name(candidate)) == normalize_display(expected)
                and _visible(candidate)
            ),
            None,
        ),
        5.0,
    )
    item.click_input()


def _create_payment_term(app: FakturamaApp, expected: str) -> None:
    _open_data_item(app, "terms of payment")
    _tab_button(app, "terms of payment", "Create a new term of payment").invoke()
    editor = wait_until(
        "new payment-term editor",
        lambda: _editor_by_base_tab(app, "New Term of Payment"),
        app.timeout,
    )
    _write(editor, "Name", expected)
    _write(editor, "Description", expected)
    _select_payment_code(editor, expected)
    for field in ("Cash discount", "Discount Days", "Net Days"):
        _write(editor, field, "0")
    save = _first_button(app.window, ("Save the current contents",))
    if save is None:
        raise _automation_failure("Payment-term editor has no save action")
    save.invoke()
    wait_until("payment-term save completion", lambda: True if not save.is_enabled() else None, app.timeout)
    wait_until(
        "saved payment-term editor",
        lambda: next(
            (
                tab
                for tab in app.window.descendants(control_type="TabItem")
                if _safe_name(tab).lstrip("*") == expected and _visible(tab)
            ),
            None,
        ),
        app.timeout,
    )


def ensure_payment_method(app: FakturamaApp | None, payment_method: str) -> str:
    """Ensure the mapped payment term exists before an Invoice is opened."""

    expected = payment_code(payment_method)
    if app is None:
        return expected
    _open_data_item(app, "terms of payment")
    pane = _payment_terms_pane(app)
    search = _labelled_edits(pane, "Search:")
    if len(search) != 1:
        raise _automation_failure("Terms-of-payment view has no unique Search field")
    search[0].set_edit_text(expected)
    decision = _visible_payment_term_decision(app, pane, expected)
    if decision == "create":
        _create_payment_term(app, expected)
        pane = _payment_terms_pane(app)
        search = _labelled_edits(pane, "Search:")
        search[0].set_edit_text(expected)
        if _visible_payment_term_decision(app, pane, expected) != "reuse":
            raise _automation_failure(f"Payment term {expected!r} was not persisted")
    if app._order_view is not None:
        app._order_view.activate()
    return expected



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


def _legacy_ensure_vat(app: FakturamaApp, order_view: OrderView, vat_percent: Decimal) -> str:
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


def _legacy_create_product(app: FakturamaApp, item: OrderItem, vat_name: str) -> None:
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


def _field_editor(app: FakturamaApp, edit_names: tuple[str, ...], combo_name: str) -> Any:
    candidates = []
    for pane in app.window.descendants(control_type='Pane'):
        if not _visible(pane):
            continue
        edits = {_safe_name(edit) for edit in pane.descendants(control_type='Edit') if _visible(edit)}
        combos = {_safe_name(combo) for combo in pane.descendants(control_type='ComboBox') if _visible(combo)}
        if set(edit_names).issubset(edits) and combo_name in combos:
            candidates.append(pane)
    if not candidates:
        raise _automation_failure('Could not locate the requested maintenance editor')
    return min(candidates, key=lambda pane: pane.element_info.rectangle.width() * pane.element_info.rectangle.height())


def _tab_button(app: FakturamaApp, tab_name: str, button_name: str) -> Any:
    tabs = [
        tab
        for tab in app.window.descendants(control_type='TabItem')
        if _visible(tab) and _safe_name(tab) == tab_name
    ]
    if len(tabs) != 1:
        raise _automation_failure(f'Expected one {tab_name!r} tab')
    tab_container = tabs[0].parent()
    toolbars = [
        toolbar
        for toolbar in tab_container.descendants(control_type='ToolBar')
        if toolbar.element_info.class_name == 'ToolbarWindow32'
        and toolbar.parent().element_info.class_name == 'SWT_Window0'
        and _visible(toolbar)
    ]
    buttons = [
        button
        for toolbar in toolbars
        for button in toolbar.descendants(control_type='Button')
        if _safe_name(button) == button_name and _visible(button)
    ]
    if len(buttons) != 1:
        raise _automation_failure(f'Expected one {button_name!r} action in {tab_name!r}')
    return buttons[0]


def _editor_by_base_tab(app: FakturamaApp, tab_name: str) -> Any | None:
    tabs = [
        tab
        for tab in app.window.descendants(control_type='TabItem')
        if _visible(tab) and _safe_name(tab).lstrip('*') == tab_name
    ]
    if not tabs:
        return None
    panes = [
        pane
        for pane in tabs[0].parent().children(control_type='Pane')
        if _safe_name(pane) == _safe_name(tabs[0]) and _visible(pane)
    ]
    return panes[0] if len(panes) == 1 else None


def ensure_vat(app: FakturamaApp, order_view: OrderView, vat_percent: Decimal) -> str:
    del order_view
    expected = f'VAT {vat_percent.normalize()}%'
    _open_data_item(app, 'VATs')
    existing_tabs = [
        tab
        for tab in app.window.descendants(control_type='TabItem')
        if _visible(tab) and _safe_name(tab).lstrip('*') == expected
    ]
    if existing_tabs:
        return expected

    new_button = _tab_button(app, 'VATs', 'Create a new tax rate')
    if new_button is None:
        raise _automation_failure(f'Missing VAT {expected} and no create action')
    new_button.invoke()
    editor = wait_until(
        'new VAT editor',
        lambda: _field_editor(app, ('Name', 'Value'), 'VAT code (E-Invoice)'),
        app.timeout,
    )
    _write(editor, 'Name', expected)
    _set_formatted_percent(editor, 'Value', vat_percent)
    _select_combo_value(editor, 'VAT code (E-Invoice)', 'S (Standard rate)')
    save = _first_button(app.window, ('Save the current contents',))
    if save is None:
        raise _automation_failure('VAT editor has no save action')
    save.invoke()
    wait_until('VAT save completion', lambda: True if not save.is_enabled() else None, app.timeout)
    wait_until(
        'saved VAT editor',
        lambda: next(
            (
                tab
                for tab in app.window.descendants(control_type='TabItem')
                if _visible(tab) and _safe_name(tab).lstrip('*') == expected
            ),
            None,
        ),
        app.timeout,
    )
    return expected


def _create_product(app: FakturamaApp, item: OrderItem, vat_name: str) -> None:
    _open_data_item(app, 'Products')
    new_button = _tab_button(app, 'Products', 'Create a new product')
    if new_button is None:
        raise _automation_failure('Product maintenance has no create action')
    new_button.invoke()
    editor = wait_until(
        'new Product editor',
        lambda: _field_editor(app, ('Item Number', 'Name'), 'VAT'),
        app.timeout,
    )
    _write(editor, 'Item Number', item.sku)
    _write(editor, 'Name', item.description)
    description = _named(editor, 'Description', ('Edit',))
    description.set_edit_text(item.description)
    price = _labelled_edits(editor, 'Price (gross)')
    cost = _labelled_edits(editor, 'cost price (net)')
    if len(price) != 1 or len(cost) != 1:
        raise _automation_failure('Product editor has no unique price fields')
    price[0].set_edit_text(str(product_gross_price(item.unit_net, item.vat_percent)))
    cost[0].set_edit_text('0')
    _write(editor, 'Stock', '0')
    _select_combo_value(editor, 'VAT', vat_name)
    save = _first_button(app.window, ('Save the current contents',))
    if save is None:
        raise _automation_failure('Product editor has no save action')
    save.invoke()
    wait_until('Product save completion', lambda: True if not save.is_enabled() else None, app.timeout)


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
            order_view.activate()
            order_view.insert_unique_product(item.sku)
        except Exception:  # noqa: BLE001
            raise error
