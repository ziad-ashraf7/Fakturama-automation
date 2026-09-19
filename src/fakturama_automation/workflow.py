"""Single Order-first image-to-cash workflow."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fakturama_automation.automation.app import FakturamaApp
from fakturama_automation.automation.documents import (
    PersistedInvoice,
    complete_and_verify_invoice,
    create_linked_invoice,
    populate_order_header,
    populate_order_items,
    save_and_verify_order,
)
from fakturama_automation.automation.masters import ensure_payment_method, resolve_debtor
from fakturama_automation.config import Settings
from fakturama_automation.domain.outcomes import (
    AutomationFailure,
    ConfigurationFailure,
    ExtractionFailure,
    ManualReviewRequired,
    OutcomeStatus,
    RunOutcome,
)
from fakturama_automation.extraction.mistral import MistralOrderExtractor

LOGGER = logging.getLogger(__name__)


def _run_id(image_path: Path) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S")
    return f"{timestamp}-{image_path.stem.casefold()}-{uuid.uuid4().hex[:8]}"


def _append_run_log(artifact_directory: Path, message: str) -> None:
    with (artifact_directory / "run.log").open("a", encoding="utf-8") as log:
        log.write(message.rstrip() + "\n")


def complete_invoice_phase(app, persisted_order, order) -> PersistedInvoice:
    """Resolve payment master data before opening the linked Invoice."""

    ensure_payment_method(app, order.payment.method)
    create_linked_invoice(app, persisted_order)
    return complete_and_verify_invoice(app, order)


def run_order_to_cash(image_path: Path, settings: Settings) -> RunOutcome:
    run_id = _run_id(image_path)
    artifact_directory = settings.artifact_root / run_id
    artifact_directory.mkdir(parents=True, exist_ok=True)
    _append_run_log(artifact_directory, f"run start: image={image_path}")
    stage = "initialization"
    try:
        stage = "extraction"
        order = MistralOrderExtractor(settings, artifact_directory).extract(image_path)
        (artifact_directory / "extracted-order.json").write_text(
            order.model_dump_json(indent=2), encoding="utf-8"
        )
        stage = "fakturama_attach"
        app = FakturamaApp.attach_or_start(settings)
        stage = "order_creation"
        order_view = app.open_unsaved_order()
        populate_order_header(order_view, order)
        stage = "master_data"
        resolve_debtor(app, order_view, order.debtor, order.payment, settings)
        stage = "order_items"
        populate_order_items(app, order_view, order)
        stage = "order_persistence"
        persisted_order = save_and_verify_order(app, order_view, order)
        stage = "invoice"
        persisted_invoice = complete_invoice_phase(app, persisted_order, order)
        stage = "invoice_persistence"
        outcome = RunOutcome(
            status=OutcomeStatus.SUCCESS,
            stage="complete",
            message=(
                f"Order {persisted_order.number} and linked Invoice "
                f"{persisted_invoice.number} verified"
            ),
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    except ManualReviewRequired as error:
        _append_run_log(artifact_directory, f"outcome: MANUAL_REVIEW stage={error.stage} message={error}")
        outcome = RunOutcome(
            status=OutcomeStatus.MANUAL_REVIEW,
            stage=error.stage,
            message=str(error),
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    except (ConfigurationFailure, ExtractionFailure, AutomationFailure) as error:
        _append_run_log(artifact_directory, f"outcome: FAILED stage={error.stage} message={error}")
        outcome = RunOutcome(
            status=OutcomeStatus.FAILED,
            stage=error.stage,
            message=str(error),
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    except Exception as error:
        LOGGER.exception("Unexpected workflow failure at %s", stage)
        _append_run_log(artifact_directory, f"outcome: FAILED stage={stage} message={error}")
        outcome = RunOutcome(
            status=OutcomeStatus.FAILED,
            stage=stage,
            message=f"Unexpected failure: {error}",
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    (artifact_directory / "outcome.json").write_text(
        outcome.model_dump_json(indent=2), encoding="utf-8"
    )
    _append_run_log(artifact_directory, f"run end: status={outcome.status}")
    return outcome
