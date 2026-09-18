from pathlib import Path

import pytest

from fakturama_automation.domain.outcomes import (
    AutomationFailure,
    ConfigurationFailure,
    ExtractionFailure,
    ManualReviewRequired,
    OutcomeStatus,
    RunOutcome,
)


def test_run_outcome_stores_the_complete_typed_result() -> None:
    outcome = RunOutcome(
        status=OutcomeStatus.SUCCESS,
        stage="invoice_verification",
        message="Invoice persisted and verified",
        run_id="run-20260918-001",
        artifact_directory=Path("artifacts/run-20260918-001"),
    )

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.stage == "invoice_verification"
    assert outcome.message == "Invoice persisted and verified"
    assert outcome.run_id == "run-20260918-001"
    assert outcome.artifact_directory == Path("artifacts/run-20260918-001")


def test_outcome_status_has_only_the_three_contract_values() -> None:
    assert {status.value for status in OutcomeStatus} == {
        "SUCCESS",
        "MANUAL_REVIEW",
        "FAILED",
    }


@pytest.mark.parametrize(
    "failure_type",
    [ManualReviewRequired, ExtractionFailure, ConfigurationFailure, AutomationFailure],
)
def test_typed_failures_preserve_stage_and_causal_message(
    failure_type: type[Exception],
) -> None:
    failure = failure_type("causal detail", stage="extraction")

    assert isinstance(failure, Exception)
    assert str(failure) == "causal detail"
    assert failure.stage == "extraction"  # type: ignore[attr-defined]
