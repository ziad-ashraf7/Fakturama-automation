from pathlib import Path

from fakturama_automation.config import Settings
from fakturama_automation.domain.outcomes import OutcomeStatus
from fakturama_automation.workflow import run_order_to_cash


def test_missing_provider_secret_is_failed(tmp_path) -> None:
    outcome = run_order_to_cash(Path("missing.png"), Settings(artifact_root=tmp_path))
    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.stage == "configuration"
