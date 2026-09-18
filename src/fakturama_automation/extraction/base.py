"""Small provider-independent boundary consumed by the workflow."""

from pathlib import Path
from typing import Protocol

from fakturama_automation.domain.models import OrderInput


class OrderExtractor(Protocol):
    def extract(self, image_path: Path) -> OrderInput:
        """Extract and validate one source order image."""
