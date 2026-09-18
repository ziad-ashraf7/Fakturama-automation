"""Small semantic UIA layer for the Fakturama 2.2.0 order editor."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeVar

from pywinauto import Application, Desktop, keyboard
from pywinauto.base_wrapper import BaseWrapper

from fakturama_automation.config import Settings
from fakturama_automation.domain.outcomes import AutomationFailure

T = TypeVar("T")
UIAWrapper = BaseWrapper

_WINDOW_TITLE_PREFIX = "Fakturama"
_WINDOW_CLASS = "SWT_Window0"
_NEW_ORDER = "New Order"
_PRODUCT_PICKER = "Select a product"
_GRID_MOVES: dict[tuple[str, str], tuple[str, ...]] = {
    ("Qty", "U.Price"): ("RIGHT",) * 6,
    ("U.Price", "VAT"): ("LEFT",) * 2,
    ("VAT", "Discount"): ("RIGHT",) * 2,
}


def _automation_failure(message: str) -> AutomationFailure:
    return AutomationFailure(message, stage="fakturama_uia")


def wait_until[T](description: str, predicate: Callable[[], T | None], timeout: float) -> T:
    """Poll a UI condition until it yields a value, bounded by ``timeout``."""

    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result is not None and result is not False:
            return result
        if time.monotonic() >= deadline:
            raise _automation_failure(f"Timed out waiting for {description}")
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def grid_key_path(start: str, target: str) -> tuple[str, ...]:
    """Return only a keyboard path verified against the Fakturama Items grid."""

    try:
        return _GRID_MOVES[(start, target)]
    except KeyError as exc:
        raise ValueError(f"No verified grid path from {start!r} to {target!r}") from exc


def _plain_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def value_for_grid_entry(column: str, value: Decimal) -> str:
    """Render a Decimal for keyboard entry, including Fakturama's discount sign."""

    if column == "Discount":
        value = -abs(value) if value else Decimal(0)
    return _plain_decimal(value)


def escape_keyboard_text(value: str) -> str:
    """Escape pywinauto key-sequence syntax while preserving literal text."""

    escaped = {
        "{": "{{}",
        "}": "{}}",
        "+": "{+}",
        "^": "{^}",
        "%": "{%}",
        "~": "{~}",
        "(": "{(}",
        ")": "{)}",
    }
    return "".join(escaped.get(character, character) for character in value)


def normalize_grid_readback(column: str, displayed: str) -> Decimal | str:
    """Normalize a visible/editor value without losing financial precision."""

    if column == "VAT":
        return " ".join(displayed.split())
    numeric = re.sub(r"[^0-9.\-]", "", displayed)
    try:
        value = Decimal(numeric)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot read {column} value from {displayed!r}") from exc
    if column == "Discount":
        return abs(value)
    return value


@dataclass(frozen=True)
class GridProbeEvidence:
    column_order: tuple[str, ...]
    read_back_values: dict[str, str]
    verified: bool


def _safe_name(control: UIAWrapper) -> str:
    try:
        return control.element_info.name or ""
    except Exception:  # noqa: BLE001
        return ""


def _visible(control: UIAWrapper) -> bool:
    try:
        return control.is_visible() and control.is_enabled()
    except Exception:  # noqa: BLE001
        return False


class FakturamaApp:
    """One attached Fakturama process with centralized semantic selectors."""

    def __init__(self, desktop: Desktop, window: UIAWrapper, timeout: float) -> None:
        self.desktop = desktop
        self.window = window
        self.timeout = timeout
        self._order_view: OrderView | None = None

    @classmethod
    def attach_or_start(cls, settings: Settings) -> FakturamaApp:
        desktop = Desktop(backend="uia")

        def locate() -> UIAWrapper | None:
            matches = [
                window
                for window in desktop.windows()
                if window.window_text().startswith(_WINDOW_TITLE_PREFIX)
                and window.element_info.class_name == _WINDOW_CLASS
            ]
            if len(matches) > 1:
                raise _automation_failure(
                    f"Expected exactly one Fakturama window, found {len(matches)}"
                )
            return matches[0] if matches else None

        window = locate()
        if window is None:
            executable = Path(settings.fakturama_exe)
            if not executable.is_file():
                raise _automation_failure(f"Fakturama executable not found: {executable}")
            Application(backend="uia").start(str(executable))
            window = wait_until("one Fakturama window", locate, settings.uia_timeout_seconds)

        if window.is_minimized():
            window.restore()
        window.set_focus()
        wait_until(
            "visible and enabled Fakturama window",
            lambda: window if _visible(window) else None,
            settings.uia_timeout_seconds,
        )
        return cls(desktop, window, settings.uia_timeout_seconds)

    def find_unique(
        self,
        name: str,
        control_type: str,
        parent: UIAWrapper | None = None,
    ) -> UIAWrapper:
        root = parent or self.window
        matches = [
            control
            for control in root.descendants(control_type=control_type)
            if _safe_name(control) == name and _visible(control)
        ]
        if len(matches) != 1:
            raise _automation_failure(
                f"Expected one visible {control_type} named {name!r}, found {len(matches)}"
            )
        return matches[0]

    def find_section_image(self, section_name: str, role: str = "upper") -> UIAWrapper:
        if self._order_view is None:
            raise _automation_failure("No open Order editor")
        return self._order_view.find_section_image(section_name, role)

    def open_unsaved_order(self) -> OrderView:
        existing = self._new_order_tabs()
        if existing:
            raise _automation_failure("A New Order editor is already open")
        action = self.find_unique("Create: New Order", "Button")
        action.invoke()
        tab = wait_until(
            "New Order editor",
            lambda: self._single_new_order_tab(),
            self.timeout,
        )
        self._order_view = OrderView(self, tab)
        return self._order_view

    def close_unsaved_editor(self) -> None:
        order = self._order_view
        if order is None:
            return
        order.activate()
        keyboard.send_keys("^{F4}")

        def closed_or_discard() -> bool | None:
            if not self._new_order_tabs():
                return True
            for name in ("Don't Save", "Discard", "Discard Changes", "No"):
                buttons = [
                    control
                    for control in self.window.descendants(control_type="Button")
                    if _safe_name(control) == name and _visible(control)
                ]
                if len(buttons) == 1:
                    buttons[0].invoke()
                    return None
            return None

        wait_until("unsaved Order editor to close without saving", closed_or_discard, self.timeout)
        self._order_view = None

    def _new_order_tabs(self) -> list[UIAWrapper]:
        return [
            tab
            for tab in self.window.descendants(control_type="TabItem")
            if _NEW_ORDER in _safe_name(tab) and _visible(tab)
        ]

    def _single_new_order_tab(self) -> UIAWrapper | None:
        tabs = self._new_order_tabs()
        if len(tabs) > 1:
            raise _automation_failure(f"Expected one New Order editor, found {len(tabs)}")
        return tabs[0] if tabs else None

    def _picker(self) -> UIAWrapper | None:
        process_id = self.window.element_info.process_id
        candidates = [window for window in self.desktop.windows() if window is not self.window]
        candidates.extend(self.window.descendants(control_type="Window"))
        matches = [
            window
            for window in candidates
            if _safe_name(window) == _PRODUCT_PICKER
            and window.element_info.process_id == process_id
            and _visible(window)
        ]
        if len(matches) > 1:
            raise _automation_failure(f"Expected one product picker, found {len(matches)}")
        return matches[0] if matches else None


class OrderView:
    """Semantic controls and verified keyboard actions for one unsaved Order."""

    def __init__(self, app: FakturamaApp, tab: UIAWrapper) -> None:
        self.app = app
        self.tab = tab
        parent = tab.parent()
        panes = [
            child
            for child in parent.children(control_type="Pane")
            if _safe_name(child) == _NEW_ORDER and _visible(child)
        ]
        if len(panes) != 1:
            raise _automation_failure(
                f"Expected one New Order editor Pane, found {len(panes)}"
            )
        self.editor = panes[0]

    @property
    def root(self) -> UIAWrapper:
        return self.editor

    def activate(self) -> None:
        try:
            self.tab.select()
        except Exception:  # noqa: BLE001
            self.tab.click_input()

    def find_section_image(self, section_name: str, role: str = "upper") -> UIAWrapper:
        if role != "upper":
            raise ValueError(f"Unsupported section image role: {role!r}")
        label = self.app.find_unique(section_name, "Text", parent=self.root)
        section = label.parent()
        images = [
            control
            for control in section.children(control_type="Image")
            if _visible(control)
        ]
        if not images:
            raise _automation_failure(f"No local Image controls found for {section_name!r}")
        images.sort(key=lambda control: control.element_info.rectangle.top)
        top = images[0].element_info.rectangle.top
        if sum(image.element_info.rectangle.top == top for image in images) != 1:
            raise _automation_failure(f"Upper Image is ambiguous for {section_name!r}")
        return images[0]

    def insert_unique_product(self, sku: str) -> None:
        if not sku:
            raise ValueError("SKU must not be empty")
        self.find_section_image("Items").click_input()
        picker = wait_until("Select a product dialog", self.app._picker, self.app.timeout)
        self.app.find_unique("Search:", "Text", parent=picker)
        search = self.app.find_unique("", "Edit", parent=picker)
        search.set_focus()
        keyboard.send_keys("^a")
        keyboard.send_keys(escape_keyboard_text(sku), with_spaces=True)

        wait_until(
            f"automatic exact selection of product {sku!r}",
            lambda: True if self.app._picker() is None else None,
            self.app.timeout,
        )
        wait_until("dirty New Order", lambda: True if self._is_dirty() else None, self.app.timeout)
        grid = self._items_grid()
        grid.set_focus()
        keyboard.send_keys("{F2}")
        self._focused_editor()
        keyboard.send_keys("{ESC}")

    def edit_grid_values(
        self,
        *,
        quantity: Decimal,
        unit_price: Decimal,
        vat: str,
        discount_percent: Decimal,
    ) -> dict[str, str]:
        grid = self._items_grid()
        grid.set_focus()
        keyboard.send_keys("{HOME}")
        read_back: dict[str, str] = {}

        read_back["Qty"] = self._edit_numeric("Qty", quantity)
        self._move("Qty", "U.Price")
        read_back["U.Price"] = self._edit_numeric("U.Price", unit_price)
        self._move("U.Price", "VAT")
        read_back["VAT"] = self._edit_vat(vat)
        self._move("VAT", "Discount")
        read_back["Discount"] = self._edit_numeric("Discount", discount_percent)
        return read_back

    def _is_dirty(self) -> bool:
        if "*" in _safe_name(self.tab):
            return True
        buttons = [
            control
            for control in self.root.descendants(control_type="Button")
            if _safe_name(control) == "Save the current contents"
        ]
        return len(buttons) == 1 and buttons[0].is_enabled()

    def _items_section(self) -> UIAWrapper:
        return self.app.find_unique("Items", "Text", parent=self.root).parent()

    def _items_grid(self) -> UIAWrapper:
        section = self._items_section()
        direct_panes = [
            pane
            for pane in section.children(control_type="Pane")
            if _safe_name(pane) == ""
            and pane.element_info.class_name == _WINDOW_CLASS
            and _visible(pane)
        ]
        if len(direct_panes) == 1:
            return direct_panes[0]
        if len(direct_panes) > 1:
            raise _automation_failure(
                f"Expected one local opaque Items grid Pane, found {len(direct_panes)}"
            )

        section_rect = section.element_info.rectangle
        sibling_content = [
            pane
            for pane in section.parent().children(control_type="Pane")
            if _safe_name(pane) == ""
            and pane.element_info.class_name == _WINDOW_CLASS
            and _visible(pane)
            and pane.element_info.rectangle.top == section_rect.top
            and pane.element_info.rectangle.left > section_rect.right
        ]
        if len(sibling_content) != 1:
            raise _automation_failure(
                "Expected one semantic Items content Pane beside the section controls"
            )
        nested_panes = [
            pane
            for pane in sibling_content[0].children(control_type="Pane")
            if _safe_name(pane) == ""
            and pane.element_info.class_name == _WINDOW_CLASS
            and _visible(pane)
        ]
        if len(nested_panes) != 1:
            raise _automation_failure(
                f"Expected one opaque Items grid inside content Pane, found {len(nested_panes)}"
            )
        return nested_panes[0]

    def _focused_editor(self) -> UIAWrapper:
        def locate() -> UIAWrapper | None:
            editors = [
                control
                for control in self._items_grid().descendants(control_type="Edit")
                if _visible(control) and control.has_keyboard_focus()
            ]
            if len(editors) > 1:
                raise _automation_failure(f"Expected one focused grid editor, found {len(editors)}")
            return editors[0] if editors else None

        return wait_until("focused Items grid editor", locate, self.app.timeout)

    def _move(self, start: str, target: str) -> None:
        for key in grid_key_path(start, target):
            keyboard.send_keys(f"{{{key}}}")

    def _edit_numeric(self, column: str, value: Decimal) -> str:
        keyboard.send_keys("{F2}")
        editor = self._focused_editor()
        editor.set_focus()
        keyboard.send_keys("^a")
        keyboard.send_keys(value_for_grid_entry(column, value))
        keyboard.send_keys("{ENTER}")
        return self._read_numeric_editor()

    def _read_numeric_editor(self) -> str:
        keyboard.send_keys("{F2}")
        editor = self._focused_editor()
        value = self._control_value(editor)
        keyboard.send_keys("{ENTER}")
        return value

    def _edit_vat(self, vat: str) -> str:
        keyboard.send_keys("{F2}")
        item = wait_until(
            f"VAT list item {vat!r}",
            lambda: self._unique_visible_list_item(vat),
            self.app.timeout,
        )
        try:
            selected = item.is_selected()
        except (AttributeError, RuntimeError):
            selected = False
        if not selected:
            item.select()
        keyboard.send_keys("{ENTER}")

        keyboard.send_keys("{F2}")
        read_back = wait_until(
            f"VAT read-back {vat!r}",
            lambda: self._unique_visible_list_item(vat),
            self.app.timeout,
        )
        try:
            selected = read_back.is_selected()
        except (AttributeError, RuntimeError) as exc:
            raise _automation_failure(
                f"VAT read-back {vat!r} does not expose selection state"
            ) from exc
        if not selected:
            raise _automation_failure(f"VAT read-back {vat!r} is not selected")
        value = _safe_name(read_back)
        keyboard.send_keys("{ENTER}")
        return value

    def _unique_visible_list_item(self, name: str) -> UIAWrapper | None:
        expected = " ".join(name.split())
        matches = [
            item
            for item in self.root.descendants(control_type="ListItem")
            if " ".join(_safe_name(item).split()) == expected and _visible(item)
        ]
        if len(matches) > 1:
            raise _automation_failure(f"VAT list item {name!r} is ambiguous")
        return matches[0] if matches else None

    @staticmethod
    def _control_value(control: UIAWrapper) -> str:
        candidates: list[str] = []
        try:
            candidates.append(str(control.iface_value.CurrentValue))
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            candidates.append(control.window_text())
        except Exception:  # noqa: BLE001, S110
            pass
        candidates.append(_safe_name(control))
        for candidate in candidates:
            if candidate:
                return candidate
        raise _automation_failure("Focused grid editor exposed no readable value")


def probe_items_grid(
    order_view: OrderView,
    *,
    quantity: Decimal,
    unit_price: Decimal,
    vat: str,
    discount_percent: Decimal,
) -> GridProbeEvidence:
    """Edit and read back the four verified Items-grid fields without saving."""

    read_back = order_view.edit_grid_values(
        quantity=quantity,
        unit_price=unit_price,
        vat=vat,
        discount_percent=discount_percent,
    )
    expected: dict[str, Decimal | str] = {
        "Qty": quantity,
        "U.Price": unit_price,
        "VAT": " ".join(vat.split()),
        "Discount": discount_percent,
    }
    discount_sign_verified = (
        discount_percent == 0
        or read_back["Discount"].lstrip().startswith("-")
    )
    verified = all(
        normalize_grid_readback(column, read_back[column]) == expected[column]
        for column in ("Qty", "U.Price", "VAT", "Discount")
    ) and discount_sign_verified
    return GridProbeEvidence(
        column_order=("Qty", "U.Price", "VAT", "Discount"),
        read_back_values=read_back,
        verified=verified,
    )
