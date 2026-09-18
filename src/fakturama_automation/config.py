"""Typed local configuration for the Fakturama automation."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal environment-backed settings for the single workflow."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mistral_api_key: SecretStr | None = None
    mistral_model: str = "mistral-ocr-latest"
    fakturama_exe: Path = Path(r"C:\Program Files\Fakturama2\Fakturama.exe")
    uia_timeout_seconds: float = Field(default=10, gt=0)
    artifact_root: Path = Path("artifacts/runs")
