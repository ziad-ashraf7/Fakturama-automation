import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from fakturama_automation.config import Settings
from fakturama_automation.domain.models import OrderInput
from fakturama_automation.domain.outcomes import (
    ConfigurationFailure,
    ExtractionFailure,
    ManualReviewRequired,
)
from fakturama_automation.extraction.mistral import (
    MistralOrderExtractor,
    OrderExtractionDraft,
    parse_annotation,
    validate_extraction,
)


def complete_annotation() -> dict[str, object]:
    return {
        "order_date": "2026-09-18",
        "external_reference": "PO-1042",
        "debtor": {
            "company": "Example GmbH",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "alias": "EXAMPLE",
            "billing_address": {
                "street": "Main Street 1",
                "zip_code": "10115",
                "city": "Berlin",
                "country": "Germany",
                "email": "ada@example.test",
                "telephone": "+49 30 123456",
            },
            "delivery_address": None,
        },
        "payment": {
            "method": "Bank Transfer",
            "status": "UNPAID",
            "payment_date": None,
        },
        "items": [
            {
                "sku": "SKU-1",
                "description": "Widget",
                "quantity": "2",
                "unit_net": "19.99",
                "vat_percent": "19",
                "discount_percent": "10",
                "source_total": "35.98",
            }
        ],
        "totals": {
            "net": "35.98",
            "vat": "6.84",
            "gross": "42.82",
            "discount_percent": "0",
            "shipping": "0.00",
        },
        "uncertain_fields": [],
    }


def test_missing_api_key_raises_typed_configuration_failure() -> None:
    with pytest.raises(ConfigurationFailure, match="MISTRAL_API_KEY") as raised:
        MistralOrderExtractor(Settings(_env_file=None))

    assert raised.value.stage == "configuration"


def test_parse_annotation_preserves_missing_and_explicit_values() -> None:
    payload = complete_annotation()
    item = payload["items"][0]  # type: ignore[index]
    item["unit_net"] = None  # type: ignore[index]
    payload["totals"].pop("shipping")  # type: ignore[union-attr]

    draft = parse_annotation(payload)

    assert isinstance(draft, OrderExtractionDraft)
    assert draft.items is not None
    assert draft.items[0].unit_net is None
    assert draft.totals is not None
    assert draft.totals.discount_percent == Decimal(0)
    assert draft.totals.shipping is None


def test_validate_extraction_returns_reconciled_strict_order() -> None:
    order = validate_extraction(parse_annotation(complete_annotation()))

    assert isinstance(order, OrderInput)
    assert order.order_date == date(2026, 9, 18)
    assert order.items[0].unit_net == Decimal("19.99")
    assert order.totals.discount_percent == Decimal(0)
    assert order.totals.shipping == Decimal("0.00")


@pytest.mark.parametrize(
    ("path", "mutate"),
    [
        (
            "items[0].unit_net",
            lambda payload: payload["items"][0].update(unit_net=None),  # type: ignore[index]
        ),
        (
            "totals.gross",
            lambda payload: payload["totals"].update(gross=None),  # type: ignore[union-attr]
        ),
    ],
)
def test_validate_extraction_requires_missing_financial_source_values(
    path: str,
    mutate: object,
) -> None:
    payload = complete_annotation()
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ManualReviewRequired, match=re.escape(path)) as raised:
        validate_extraction(parse_annotation(payload))

    assert raised.value.stage == "extraction_validation"


def test_validate_extraction_requires_review_for_uncertain_required_data() -> None:
    payload = complete_annotation()
    payload["uncertain_fields"] = ["items[0].vat_percent"]

    with pytest.raises(ManualReviewRequired, match=r"items\[0\]\.vat_percent"):
        validate_extraction(parse_annotation(payload))


@pytest.mark.parametrize(
    "path",
    ["totals.discount_percent", "totals.shipping"],
)
def test_validate_extraction_requires_review_for_uncertain_optional_financial_data(
    path: str,
) -> None:
    payload = complete_annotation()
    payload["uncertain_fields"] = [path]

    with pytest.raises(ManualReviewRequired, match=re.escape(path)) as raised:
        validate_extraction(parse_annotation(payload))

    assert raised.value.stage == "extraction_validation"


def test_validate_extraction_requires_payment_date_for_paid_source() -> None:
    payload = complete_annotation()
    payload["payment"].update(status="PAID", payment_date=None)  # type: ignore[union-attr]

    with pytest.raises(ManualReviewRequired, match="payment.payment_date"):
        validate_extraction(parse_annotation(payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"items": "not-a-list"},
        {"items": [{"unit_net": "not-a-decimal"}]},
        {"unexpected_provider_field": True},
    ],
)
def test_parse_annotation_wraps_malformed_provider_data(payload: dict[str, object]) -> None:
    with pytest.raises(ExtractionFailure, match="Malformed Mistral annotation") as raised:
        parse_annotation(payload)

    assert raised.value.stage == "extraction"


def test_extract_uses_official_sdk_boundary_and_validates_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "order.png"
    image_path.write_bytes(b"fake-png")
    process = Mock(
        return_value=SimpleNamespace(document_annotation=json.dumps(complete_annotation()))
    )
    client = SimpleNamespace(ocr=SimpleNamespace(process=process))
    mistral = Mock(return_value=client)
    response_format = object()
    format_builder = Mock(return_value=response_format)
    monkeypatch.setattr("fakturama_automation.extraction.mistral.Mistral", mistral)
    monkeypatch.setattr(
        "fakturama_automation.extraction.mistral.response_format_from_pydantic_model",
        format_builder,
    )

    extractor = MistralOrderExtractor(
        Settings(mistral_api_key=SecretStr("test-key"), _env_file=None)
    )
    order = extractor.extract(image_path)

    assert order.external_reference == "PO-1042"
    mistral.assert_called_once_with(api_key="test-key")
    format_builder.assert_called_once_with(OrderExtractionDraft)
    request = process.call_args.kwargs
    assert request["model"] == "mistral-ocr-latest"
    assert request["document"].type == "image_url"
    assert request["document"].image_url.startswith("data:image/png;base64,")
    assert request["document_annotation_format"] is response_format
    assert "uncertain_fields" in request["document_annotation_prompt"]


def test_extract_wraps_sdk_failures_as_typed_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "order.jpg"
    image_path.write_bytes(b"fake-jpeg")
    process = Mock(side_effect=RuntimeError("network unavailable"))
    client = SimpleNamespace(ocr=SimpleNamespace(process=process))
    monkeypatch.setattr(
        "fakturama_automation.extraction.mistral.Mistral", Mock(return_value=client)
    )

    extractor = MistralOrderExtractor(
        Settings(mistral_api_key=SecretStr("test-key"), _env_file=None)
    )

    with pytest.raises(ExtractionFailure, match="Mistral OCR request failed") as raised:
        extractor.extract(image_path)

    assert raised.value.stage == "extraction"


def test_extract_rejects_non_json_annotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "order.webp"
    image_path.write_bytes(b"fake-webp")
    response = SimpleNamespace(document_annotation="not json")
    client = SimpleNamespace(ocr=SimpleNamespace(process=Mock(return_value=response)))
    monkeypatch.setattr(
        "fakturama_automation.extraction.mistral.Mistral", Mock(return_value=client)
    )

    extractor = MistralOrderExtractor(
        Settings(mistral_api_key=SecretStr("test-key"), _env_file=None)
    )

    with pytest.raises(ExtractionFailure, match="Malformed Mistral annotation"):
        extractor.extract(image_path)


class InaccessibleAnnotation:
    @property
    def document_annotation(self) -> str:
        raise RuntimeError("annotation unavailable")


@pytest.mark.parametrize(
    "response",
    [SimpleNamespace(), InaccessibleAnnotation(), SimpleNamespace(document_annotation=None)],
)
def test_extract_wraps_unusable_sdk_response_annotation(
    response: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "order.png"
    image_path.write_bytes(b"fake-png")
    client = SimpleNamespace(ocr=SimpleNamespace(process=Mock(return_value=response)))
    monkeypatch.setattr(
        "fakturama_automation.extraction.mistral.Mistral", Mock(return_value=client)
    )
    extractor = MistralOrderExtractor(
        Settings(mistral_api_key=SecretStr("test-key"), _env_file=None)
    )

    with pytest.raises(ExtractionFailure, match="Malformed Mistral annotation") as raised:
        extractor.extract(image_path)

    assert raised.value.stage == "extraction"
