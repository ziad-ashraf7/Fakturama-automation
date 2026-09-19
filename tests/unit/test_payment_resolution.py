from pathlib import Path
from types import SimpleNamespace

import pytest

from fakturama_automation import workflow
from fakturama_automation.automation import masters
from fakturama_automation.automation.masters import payment_term_decision
from fakturama_automation.domain.outcomes import MasterDataConflict, OutcomeStatus
from fakturama_automation.workflow import complete_invoice_phase


def _order() -> SimpleNamespace:
    return SimpleNamespace(payment=SimpleNamespace(method="Bank Transfer"))


def test_existing_credit_transfer_is_reused_without_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        "fakturama_automation.workflow.ensure_payment_method",
        lambda _app, _method: events.append("reuse") or "Credit transfer",
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.create_linked_invoice",
        lambda _app, _order: events.append("invoice") or object(),
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.complete_and_verify_invoice",
        lambda _app, _order: events.append("select") or object(),
    )

    complete_invoice_phase(object(), object(), _order())

    assert events == ["reuse", "invoice", "select"]


def test_missing_credit_transfer_is_created_and_persisted_before_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        "fakturama_automation.workflow.ensure_payment_method",
        lambda _app, _method: events.extend(["create", "persist"]) or "Credit transfer",
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.create_linked_invoice",
        lambda _app, _order: events.append("invoice") or object(),
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.complete_and_verify_invoice",
        lambda _app, _order: events.append("select") or object(),
    )

    complete_invoice_phase(object(), object(), _order())

    assert events == ["create", "persist", "invoice", "select"]


def test_exact_payment_term_decision_never_creates_a_duplicate() -> None:
    assert payment_term_decision(("Cash", "Credit transfer"), "Credit transfer") == "reuse"


def test_duplicate_exact_payment_terms_are_manual_review() -> None:
    with pytest.raises(MasterDataConflict, match="Credit transfer"):
        payment_term_decision(("Credit transfer", "Credit transfer"), "Credit transfer")


def test_invoice_phase_cannot_open_invoice_before_payment_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        "fakturama_automation.workflow.ensure_payment_method",
        lambda _app, _method: events.append("payment-ready") or "Credit transfer",
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.create_linked_invoice",
        lambda _app, _order: events.append("invoice-opened") or object(),
    )
    monkeypatch.setattr(
        "fakturama_automation.workflow.complete_and_verify_invoice",
        lambda _app, _order: events.append("invoice-selected") or object(),
    )

    complete_invoice_phase(object(), object(), _order())

    assert events.index("payment-ready") < events.index("invoice-opened")


def test_run_order_to_cash_executes_the_order_body_after_payment_phase_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    order = SimpleNamespace(
        payment=SimpleNamespace(method="Bank Transfer"),
        debtor=object(),
        model_dump_json=lambda indent=2: "{}",
    )
    app = SimpleNamespace(open_unsaved_order=lambda: events.append("new-order") or object())

    class FakeExtractor:
        def __init__(self, _settings: object, _artifact_directory: Path) -> None:
            pass

        def extract(self, _image_path: Path) -> SimpleNamespace:
            events.append("extract")
            return order

    monkeypatch.setattr(workflow, "MistralOrderExtractor", FakeExtractor)
    monkeypatch.setattr(
        workflow.FakturamaApp,
        "attach_or_start",
        lambda _settings: events.append("attach") or app,
    )
    monkeypatch.setattr(
        workflow,
        "populate_order_header",
        lambda _view, _order: events.append("header"),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_debtor",
        lambda _app, _view, _debtor, _payment, _settings: events.append("debtor"),
    )
    monkeypatch.setattr(
        workflow,
        "populate_order_items",
        lambda _app, _view, _order: events.append("items"),
    )
    monkeypatch.setattr(
        workflow,
        "save_and_verify_order",
        lambda _app, _view, _order: events.append("order-saved")
        or SimpleNamespace(number="PO000001"),
    )
    monkeypatch.setattr(
        workflow,
        "complete_invoice_phase",
        lambda _app, _saved_order, _order: events.append("invoice")
        or SimpleNamespace(number="INV000001"),
    )

    outcome = workflow.run_order_to_cash(
        Path("samples/input/Picture1.jpg"),
        workflow.Settings(artifact_root=tmp_path),
    )

    assert outcome.status is OutcomeStatus.SUCCESS
    assert events == [
        "extract",
        "attach",
        "new-order",
        "header",
        "debtor",
        "items",
        "order-saved",
        "invoice",
    ]


def test_payment_lookup_opens_terms_master_before_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    app = SimpleNamespace(settings=object(), timeout=1, _order_view=None)
    search = SimpleNamespace(set_edit_text=lambda _value: events.append("search"))

    monkeypatch.setattr(
        masters,
        "_open_data_item",
        lambda _app, name: events.append(f"open:{name}"),
    )
    monkeypatch.setattr(
        masters,
        "_payment_terms_pane",
        lambda _app: events.append("pane") or object(),
    )
    monkeypatch.setattr(masters, "_labelled_edits", lambda _pane, _label: [search])
    monkeypatch.setattr(
        masters,
        "_visible_payment_term_decision",
        lambda _app, _pane, _expected: events.append("decision") or "reuse",
    )

    assert masters.ensure_payment_method(app, "Bank Transfer") == "Credit transfer"
    assert events == ["open:terms of payment", "pane", "search", "decision"]


def test_payment_term_lookup_uses_name_column_when_header_is_ocr_visible() -> None:
    markdown = """\
| Standard | Name | Description | Discount | Disc. Days | Net Days |
| --- | --- | --- | --- | --- | --- |
|  | Credit transfer | Credit transfer | 0% | 0 | 0 |
"""

    assert masters.payment_term_lookup_decision(markdown, "Credit transfer") == "reuse"


def test_payment_term_lookup_reuses_exact_row_when_name_header_is_missing() -> None:
    markdown = """\
| Standard | Description | Discount | Disc. Days | Net Days |
| --- | --- | --- | --- | --- |
|  | Credit transfer | 0% | 0 | 0 |
"""

    assert masters.payment_term_lookup_decision(markdown, "Credit transfer") == "reuse"


def test_payment_term_lookup_creates_when_headerless_filtered_table_is_empty() -> None:
    markdown = """\
| Standard | Description | Discount | Disc. Days | Net Days |
| --- | --- | --- | --- | --- |
"""

    assert masters.payment_term_lookup_decision(markdown, "Credit transfer") == "create"


def test_payment_term_lookup_rejects_ambiguous_headerless_exact_rows() -> None:
    markdown = """\
| Standard | Description | Discount | Disc. Days | Net Days |
| --- | --- | --- | --- | --- |
|  | Credit transfer | Credit transfer | 0% | 0 |
|  | Credit transfer | Credit transfer | 0% | 0 |
"""

    with pytest.raises(MasterDataConflict, match="Credit transfer"):
        masters.payment_term_lookup_decision(markdown, "Credit transfer")
