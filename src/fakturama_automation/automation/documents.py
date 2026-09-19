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
    wait_until,
)
from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.outcomes import AutomationFailure
from fakturama_automation.domain.rules import MONEY_QUANTUM, line_total, payment_code


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


def _normalize_document_value(value: str) -> str:
    return " ".join(value.split()).casefold()


def verify_persisted_invoice(
    *,
    number: str,
    external_reference: str,
    total: Decimal,
    state: str,
    document_row: dict[str, str] | None,
) -> PersistedInvoice:
    normalized_number = _normalize_document_value(number)
    if not normalized_number or normalized_number == "new":
        raise _automation_failure(
            f"Generated Invoice number was not assigned after Save: {number!r}"
        )
    if document_row is None:
        raise _automation_failure(
            f"Persisted Invoice {number!r} has no matching Documents row"
        )
    actual_number = _normalize_document_value(document_row.get("Document", ""))
    if actual_number != normalized_number:
        raise _automation_failure(
            f"Documents Invoice number mismatch: expected {number!r}, "
            f"got {document_row.get('Document', '')!r}"
        )
    actual_reference = _normalize_document_value(document_row.get("Cust.Ref.", ""))
    if actual_reference != _normalize_document_value(external_reference):
        raise _automation_failure(
            f"Documents Invoice Cust.Ref. mismatch: expected {external_reference!r}, "
            f"got {document_row.get('Cust.Ref.', '')!r}"
        )
    try:
        actual_total = normalize_grid_readback("Total", document_row.get("Total", ""))
    except ValueError as error:
        raise _automation_failure("Documents Invoice total was unreadable") from error
    expected_total = total.quantize(MONEY_QUANTUM)
    if actual_total != expected_total:
        raise _automation_failure(
            f"Documents Invoice Total mismatch: expected {expected_total!s}, "
            f"got {actual_total!s}"
        )
    actual_state = _normalize_document_value(document_row.get("State", ""))
    if actual_state != _normalize_document_value(state):
        raise _automation_failure(
            f"Documents Invoice state mismatch: expected {state!r}, "
            f"got {document_row.get('State', '')!r}"
        )
    return PersistedInvoice(number=number, total=expected_total, state=state)


def _document_rows_from_markdown(markdown: str) -> tuple[dict[str, str], ...]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(_normalize_document_value(cell) == "document" for cell in _markdown_cells(line))
        ),
        None,
    )
    if header_index is None:
        raise _automation_failure("Documents OCR has no Document column")
    headers = _markdown_cells(lines[header_index])
    separator_index = next(
        (
            index
            for index, line in enumerate(lines[header_index + 1 :], header_index + 1)
            if _is_markdown_separator(_markdown_cells(line))
        ),
        None,
    )
    data_start = separator_index + 1 if separator_index is not None else header_index + 1
    rows: list[dict[str, str]] = []
    for line in lines[data_start:]:
        cells = _markdown_cells(line)
        if not cells or _is_markdown_separator(cells):
            continue
        rows.append(
            {
                headers[index]: cells[index].strip()
                for index in range(min(len(headers), len(cells)))
                if headers[index].strip()
            }
        )
    return tuple(rows)


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        cell.replace("-", "").replace(":", "").strip() == "" for cell in cells
    )


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


def _set_segmented_date(root: Any, control_name: str, target_date: date) -> None:
    control = _control(root, control_name)
    rect = control.element_info.rectangle
    control.click_input(coords=(max(1, rect.width() // 25), max(1, rect.height() // 2)))
    keyboard.send_keys("{HOME}")
    keyboard.send_keys(str(target_date.month))
    keyboard.send_keys("{ENTER}")
    keyboard.send_keys(str(target_date.day))
    keyboard.send_keys("{ENTER}")
    keyboard.send_keys(str(target_date.year))
    keyboard.send_keys("{ENTER}")
    actual = _read(root, control_name).strip()
    expected = f"{target_date.strftime('%b')} {target_date.day}, {target_date.year}"
    compact_expected = f"{target_date.strftime('%b')} {target_date.day}, {target_date.strftime('%y')}"
    if actual not in {expected, compact_expected}:
        raise _automation_failure(
            f"{control_name} read-back mismatch: expected {expected!r}, got {actual!r}"
        )


def _set_order_date(root: Any, order_date: date) -> None:
    _set_segmented_date(root, "Date", order_date)


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


def _set_currency_value(root: Any, name: str, value: Decimal) -> None:
    control = _control(root, name)
    control.click_input()
    keyboard.send_keys("{HOME}")
    keyboard.send_keys("+{END}")
    keyboard.send_keys(format(value, "f"))
    keyboard.send_keys("{TAB}")
    actual = normalize_grid_readback(name, _read(root, name))
    expected = value.quantize(MONEY_QUANTUM)
    if actual != expected:
        raise _automation_failure(
            f"{name} read-back mismatch: expected {expected!s}, got {actual!s}"
        )


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


def _select_vat_mode(root: Any) -> None:
    combos = [
        combo
        for combo in root.descendants(control_type="ComboBox")
        if _safe_name(combo) == "VAT" and _visible(combo)
    ]
    if len(combos) != 1:
        raise _automation_failure(
            f"Expected one semantic VAT-mode selector, found {len(combos)}"
        )
    combos[0].select("With VAT")
    actual = " ".join(_selected_control_value(combos[0]).split())
    if actual.casefold() != "with vat":
        raise _automation_failure(
            f"VAT mode read-back mismatch: expected 'With VAT', got {actual!r}"
        )


def _select_invoice_payment_method(root: Any, expected: str) -> Any:
    paid_control = _control(root, "paid", ("CheckBox",))
    paid_rect = paid_control.element_info.rectangle
    candidates = [
        combo
        for combo in root.descendants(control_type="ComboBox")
        if not _safe_name(combo)
        and _visible(combo)
        and combo.element_info.rectangle.top < paid_rect.bottom
        and combo.element_info.rectangle.bottom > paid_rect.top
    ]
    if len(candidates) != 1:
        raise _automation_failure(
            f"Expected one Invoice payment-method selector, found {len(candidates)}"
        )
    combo = candidates[0]
    opens = [
        button
        for button in combo.descendants(control_type="Button")
        if _safe_name(button) == "Open" and _visible(button)
    ]
    if len(opens) != 1:
        raise _automation_failure("Invoice payment-method selector has no unique Open action")
    opens[0].invoke()
    item = wait_until(
        f"Invoice payment method {expected!r}",
        lambda: next(
            (
                candidate
                for candidate in root.descendants(control_type="ListItem")
                if _safe_name(candidate) == expected and _visible(candidate)
            ),
            None,
        ),
        5.0,
    )
    item.click_input()
    actual = " ".join(_selected_control_value(combo).split())
    if actual.casefold() != expected.casefold():
        raise _automation_failure(
            f"Invoice payment-method read-back mismatch: expected {expected!r}, got {actual!r}"
        )
    return combo


def populate_order_header(order_view: OrderView, order: OrderInput) -> None:
    root = order_view.root
    _set_order_date(root, order.order_date)
    _write(root, "Cust.Ref.", order.external_reference)
    _select_net_price_mode(root)
    _select_vat_mode(root)
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


def _documents_pane(app: FakturamaApp) -> Any:
    tab = app.find_unique("Documents", "TabItem")
    tab.click_input()
    return next(
        (
            pane
            for pane in tab.parent().children(control_type="Pane")
            if _safe_name(pane) == "Documents" and _visible(pane)
        ),
        None,
    )


def _filter_documents_by_reference(app: FakturamaApp, external_reference: str) -> None:
    pane = _documents_pane(app)
    if pane is None:
        raise _automation_failure("Documents view has no semantic content Pane")
    search = _control(pane, "Search:")
    search.set_edit_text(external_reference)


def _documents_rows(app: FakturamaApp) -> tuple[dict[str, str], ...]:
    pane = _documents_pane(app)
    if pane is None:
        raise _automation_failure("Documents view has no semantic content Pane")
    settings = app.settings
    if settings is None or settings.mistral_api_key is None:
        raise _automation_failure("MISTRAL_API_KEY is required for Documents verification")
    from fakturama_automation.automation.visual_items import _ocr_markdown

    return _document_rows_from_markdown(
        _ocr_markdown(pane.capture_as_image(), settings)
    )


def save_and_verify_order(app: FakturamaApp, order_view: OrderView, order: OrderInput) -> PersistedOrder:
    number = _read(order_view.root, "No.")
    _invoke_named(app.window, "Save the current contents")
    _filter_documents_by_reference(app, order.external_reference)
    wait_until(
        "saved Order editor",
        lambda: next(
            (
                tab
                for tab in app.window.descendants(control_type="TabItem")
                if _safe_name(tab) == number and _visible(tab)
            ),
            None,
        ),
        app.timeout,
    )
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
    payment_combo = _select_invoice_payment_method(root, payment_code(order.payment.method))
    is_paid = order.payment.status == "PAID"
    paid_control = None
    if is_paid:
        if order.payment.payment_date is None:
            raise _automation_failure("Paid source is missing Payment Date")
        paid_controls = [
            control
            for control in root.descendants(control_type="CheckBox")
            if _safe_name(control).casefold() == "paid" and _visible(control)
        ]
        if len(paid_controls) != 1:
            raise _automation_failure(
                f"Expected one visible paid checkbox, found {len(paid_controls)}"
            )
        paid_control = paid_controls[0]
        if paid_control.get_toggle_state() != 1:
            paid_control.click_input()
        _set_segmented_date(root, "at", order.payment.payment_date)
        _set_currency_value(root, "Value", order.totals.gross)
    _invoke_named(root, "Save the current contents")

    def generated_number() -> str | None:
        try:
            number = _read(root, "No.").strip()
        except AutomationFailure:
            return None
        return number if _normalize_document_value(number) not in {"", "new"} else None

    number = wait_until("generated Invoice number after Save", generated_number, app.timeout)
    expected_payment = payment_code(order.payment.method)
    if _selected_control_value(payment_combo).strip().casefold() != expected_payment.casefold():
        raise _automation_failure("Invoice payment method was not retained after Save")
    if is_paid:
        if paid_control is None or paid_control.get_toggle_state() != 1:
            raise _automation_failure("Invoice paid state was not retained after Save")
        expected_date = order.payment.payment_date.strftime("%b %d, %Y").replace(" 0", " ")
        compact_date = order.payment.payment_date.strftime("%b %d, %y").replace(" 0", " ")
        actual_date = _read(root, "at").strip()
        if actual_date not in {expected_date, compact_date}:
            raise _automation_failure(
                f"Invoice payment date mismatch after Save: expected {expected_date!r}, "
                f"got {actual_date!r}"
            )
        actual_value = normalize_grid_readback("Value", _read(root, "Value"))
        expected_value = order.totals.gross.quantize(MONEY_QUANTUM)
        if actual_value != expected_value:
            raise _automation_failure(
                f"Invoice payment value mismatch after Save: expected {expected_value!s}, "
                f"got {actual_value!s}"
            )
    _filter_documents_by_reference(app, order.external_reference)
    rows = wait_until(
        "persisted Invoice Documents row",
        lambda: _documents_rows(app) or None,
        app.timeout,
    )
    row = next(
        (
            candidate
            for candidate in rows
            if _normalize_document_value(candidate.get("Document", ""))
            == _normalize_document_value(number)
        ),
        None,
    )
    return verify_persisted_invoice(
        number=number,
        external_reference=order.external_reference,
        total=order.totals.gross,
        state="paid" if is_paid else "open",
        document_row=row,
    )
