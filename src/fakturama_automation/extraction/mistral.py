"""Structured order extraction through Mistral Document AI OCR."""

import base64
import json
import mimetypes
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from mistralai.client import Mistral
from mistralai.client.models import ImageURLChunk
from mistralai.extra import response_format_from_pydantic_model
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fakturama_automation.config import Settings
from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.outcomes import (
    ConfigurationFailure,
    ExtractionFailure,
    ManualReviewRequired,
)
from fakturama_automation.domain.rules import reconcile_order

ANNOTATION_PROMPT = """Extract exactly the source order data into the supplied schema.
Use null for missing values and never infer or calculate financial values. Add every field whose
source value is ambiguous or illegible to uncertain_fields using paths such as
items[0].unit_net. Preserve whether order-level discount_percent and shipping were omitted.
"""


class DraftModel(BaseModel):
    """Permissive source DTO that still rejects malformed provider structure."""

    model_config = ConfigDict(extra="forbid")


class AddressExtractionDraft(DraftModel):
    street: str | None = None
    zip_code: str | None = None
    city: str | None = None
    country: str | None = None
    email: str | None = None
    telephone: str | None = None
    additional_name: str | None = None
    address_specification: str | None = None
    district: str | None = None


class DebtorExtractionDraft(DraftModel):
    company: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    alias: str | None = None
    billing_address: AddressExtractionDraft | None = None
    delivery_address: AddressExtractionDraft | None = None


class PaymentExtractionDraft(DraftModel):
    method: str | None = None
    status: Literal["PAID", "UNPAID"] | None = None
    payment_date: date | None = None


class OrderItemExtractionDraft(DraftModel):
    sku: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    unit_net: Decimal | None = None
    vat_percent: Decimal | None = None
    discount_percent: Decimal | None = None
    source_total: Decimal | None = None


class OrderTotalsExtractionDraft(DraftModel):
    net: Decimal | None = None
    vat: Decimal | None = None
    gross: Decimal | None = None
    discount_percent: Decimal | None = None
    shipping: Decimal | None = None


class OrderExtractionDraft(DraftModel):
    """Potentially incomplete structured annotation returned by Mistral."""

    order_date: date | None = None
    external_reference: str | None = None
    debtor: DebtorExtractionDraft | None = None
    payment: PaymentExtractionDraft | None = None
    items: list[OrderItemExtractionDraft] | None = None
    totals: OrderTotalsExtractionDraft | None = None
    uncertain_fields: list[str] = Field(default_factory=list)


def parse_annotation(payload: dict[str, object]) -> OrderExtractionDraft:
    """Parse an untrusted structured annotation into the permissive draft DTO."""

    try:
        return OrderExtractionDraft.model_validate(payload)
    except (TypeError, ValidationError, ValueError) as error:
        raise ExtractionFailure(
            "Malformed Mistral annotation",
            stage="extraction",
        ) from error


def _required[T](value: T | None, path: str, missing: list[str]) -> T | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        missing.append(path)
    return value


def _required_address(
    address: AddressExtractionDraft | None,
    path: str,
    missing: list[str],
) -> None:
    if _required(address, path, missing) is None:
        return
    _required(address.street, f"{path}.street", missing)
    _required(address.zip_code, f"{path}.zip_code", missing)
    _required(address.city, f"{path}.city", missing)
    _required(address.country, f"{path}.country", missing)


def _required_paths(draft: OrderExtractionDraft) -> list[str]:
    missing: list[str] = []
    _required(draft.order_date, "order_date", missing)
    _required(draft.external_reference, "external_reference", missing)

    if _required(draft.debtor, "debtor", missing) is not None:
        _required(draft.debtor.company, "debtor.company", missing)
        _required(draft.debtor.alias, "debtor.alias", missing)
        _required_address(draft.debtor.billing_address, "debtor.billing_address", missing)

    if _required(draft.payment, "payment", missing) is not None:
        _required(draft.payment.method, "payment.method", missing)
        _required(draft.payment.status, "payment.status", missing)
        if draft.payment.status == "PAID":
            _required(draft.payment.payment_date, "payment.payment_date", missing)

    if not draft.items:
        missing.append("items")
    else:
        for index, item in enumerate(draft.items):
            prefix = f"items[{index}]"
            _required(item.sku, f"{prefix}.sku", missing)
            _required(item.description, f"{prefix}.description", missing)
            _required(item.quantity, f"{prefix}.quantity", missing)
            _required(item.unit_net, f"{prefix}.unit_net", missing)
            _required(item.vat_percent, f"{prefix}.vat_percent", missing)
            _required(item.discount_percent, f"{prefix}.discount_percent", missing)
            _required(item.source_total, f"{prefix}.source_total", missing)

    if _required(draft.totals, "totals", missing) is not None:
        _required(draft.totals.net, "totals.net", missing)
        _required(draft.totals.vat, "totals.vat", missing)
        _required(draft.totals.gross, "totals.gross", missing)
    return missing


def _is_required_uncertainty(path: str, required_paths: set[str]) -> bool:
    return any(
        required == path
        or required.startswith((f"{path}.", f"{path}["))
        for required in required_paths
    )


def validate_extraction(draft: OrderExtractionDraft) -> OrderInput:
    """Promote only complete and reconciled source data into strict workflow input."""

    missing = _required_paths(draft)
    all_required = {
        "order_date",
        "external_reference",
        "debtor.company",
        "debtor.alias",
        "debtor.billing_address.street",
        "debtor.billing_address.zip_code",
        "debtor.billing_address.city",
        "debtor.billing_address.country",
        "payment.method",
        "payment.status",
        "payment.payment_date",
        "totals.net",
        "totals.vat",
        "totals.gross",
    }
    if draft.items:
        for index in range(len(draft.items)):
            all_required.update(
                f"items[{index}].{field}"
                for field in (
                    "sku",
                    "description",
                    "quantity",
                    "unit_net",
                    "vat_percent",
                    "discount_percent",
                    "source_total",
                )
            )
    uncertain = [
        path for path in draft.uncertain_fields if _is_required_uncertainty(path, all_required)
    ]
    if missing or uncertain:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if uncertain:
            details.append(f"uncertain: {', '.join(uncertain)}")
        raise ManualReviewRequired(
            f"Required source data needs review ({'; '.join(details)})",
            stage="extraction_validation",
        )

    try:
        order = OrderInput.model_validate(draft.model_dump(exclude={"uncertain_fields"}))
    except ValidationError as error:
        raise ManualReviewRequired(
            "Extracted source values failed order validation",
            stage="extraction_validation",
        ) from error
    reconcile_order(order)
    return order


class MistralOrderExtractor:
    """The single supported extraction provider."""

    def __init__(self, settings: Settings) -> None:
        api_key = settings.mistral_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise ConfigurationFailure(
                "MISTRAL_API_KEY is required for Mistral extraction",
                stage="configuration",
            )
        self._settings = settings
        try:
            self._client = Mistral(api_key=api_key.get_secret_value())
        except Exception as error:
            raise ExtractionFailure(
                "Mistral SDK initialization failed",
                stage="extraction",
            ) from error

    def extract(self, image_path: Path) -> OrderInput:
        """Submit an image to Mistral, then parse, validate, and reconcile it."""

        try:
            media_type = mimetypes.guess_type(image_path.name)[0]
            if image_path.suffix.casefold() == '.webp':
                media_type = 'image/webp'
            if media_type is None or not media_type.startswith("image/"):
                raise ValueError(f"Unsupported image type: {image_path.suffix or '<none>'}")
            encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
            image_chunk = ImageURLChunk(
                image_url=f"data:{media_type};base64,{encoded_image}",
            )
            response = self._client.ocr.process(
                model=self._settings.mistral_model,
                document=image_chunk,
                document_annotation_format=response_format_from_pydantic_model(
                    OrderExtractionDraft
                ),
                document_annotation_prompt=ANNOTATION_PROMPT,
            )
        except Exception as error:
            raise ExtractionFailure(
                "Mistral OCR request failed",
                stage="extraction",
            ) from error

        annotation = response.document_annotation
        if not isinstance(annotation, str):
            raise ExtractionFailure(
                "Malformed Mistral annotation",
                stage="extraction",
            )
        try:
            payload = json.loads(annotation, parse_float=Decimal)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ExtractionFailure(
                "Malformed Mistral annotation",
                stage="extraction",
            ) from error
        if not isinstance(payload, dict):
            raise ExtractionFailure(
                "Malformed Mistral annotation",
                stage="extraction",
            )
        return validate_extraction(parse_annotation(payload))
