"""Typed terminal outcomes and failures for workflow boundaries."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class OutcomeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"


class RunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OutcomeStatus
    stage: str = Field(min_length=1)
    message: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    artifact_directory: Path


class DomainFailure(Exception):
    """Base class for failures intentionally handled by the workflow boundary."""

    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


class ManualReviewRequired(DomainFailure):
    """Source ambiguity or a business-data conflict needs human resolution."""


class ExtractionFailure(DomainFailure):
    """The extraction provider returned unusable data or failed technically."""


class ConfigurationFailure(DomainFailure):
    """Required local or provider configuration is unavailable."""


class AutomationFailure(DomainFailure):
    """Fakturama automation could not safely complete or verify an action."""


class DomainValidationError(ManualReviewRequired):
    """Validated source values fail deterministic domain reconciliation."""


class MasterDataConflict(ManualReviewRequired):
    """A named master record exists with a conflicting definition."""
