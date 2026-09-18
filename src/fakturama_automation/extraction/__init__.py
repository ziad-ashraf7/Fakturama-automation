"""Order extraction through the sole configured Mistral provider."""

from fakturama_automation.extraction.base import OrderExtractor
from fakturama_automation.extraction.mistral import MistralOrderExtractor

__all__ = ["MistralOrderExtractor", "OrderExtractor"]
