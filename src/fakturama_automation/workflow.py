"""Single Order-first image-to-cash workflow."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fakturama_automation.automation.app import FakturamaApp
from fakturama_automation.automation.documents import (
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


def run_order_to_cash(image_path: Path, settings: Settings) -> RunOutcome:
    run_id = uuid.uuid4().hex
    artifact_directory = settings.artifact_root / run_id
    artifact_directory.mkdir(parents=True, exist_ok=True)
    stage = "initialization"
    try:
        stage = "extraction"
        order = MistralOrderExtractor(settings).extract(image_path)
        (artifact_directory / "extracted-order.json").write_text(
            order.model_dump_json(indent=2), encoding="utf-8"
        )
        stage = "fakturama_attach"
        app = FakturamaApp.attach_or_start(settings)
        stage = "order_creation"
        order_view = app.open_unsaved_order()
        populate_order_header(order_view, order)
        stage = "master_data"
        ensure_payment_method(app, order.payment.method)
        resolve_debtor(app, order_view, order.debtor, order.payment)
        stage = "order_items"
        populate_order_items(app, order_view, order)
        stage = "order_persistence"
        persisted_order = save_and_verify_order(app, order_view, order)
        stage = "invoice"
        create_linked_invoice(app, persisted_order)
        stage = "invoice_persistence"
        persisted_invoice = complete_and_verify_invoice(app, order)
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
        outcome = RunOutcome(
            status=OutcomeStatus.MANUAL_REVIEW,
            stage=error.stage,
            message=str(error),
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    except (ConfigurationFailure, ExtractionFailure, AutomationFailure) as error:
        outcome = RunOutcome(
            status=OutcomeStatus.FAILED,
            stage=error.stage,
            message=str(error),
            run_id=run_id,
            artifact_directory=artifact_directory,
        )
    except Exception as error:
        LOGGER.exception("Unexpected workflow failure at %s", stage)
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
    return outcome
