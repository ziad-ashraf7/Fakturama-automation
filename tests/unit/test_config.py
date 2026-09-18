from pathlib import Path

from fakturama_automation.config import Settings


def test_settings_do_not_require_a_mistral_api_key() -> None:
    settings = Settings(_env_file=None)

    assert settings.mistral_api_key is None
    assert settings.mistral_model == "mistral-ocr-latest"
    assert settings.fakturama_exe == Path(r"C:\Program Files\Fakturama2\Fakturama.exe")
    assert settings.uia_timeout_seconds == 10
    assert settings.artifact_root == Path("artifacts/runs")
