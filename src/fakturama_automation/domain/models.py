"""Strict input models for one source order."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Base configuration shared by all source-domain models."""

    model_config = ConfigDict(extra="forbid")


class Address(DomainModel):
    street: str = Field(min_length=1)
    zip_code: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)
    email: str | None = None
    telephone: str | None = None
    additional_name: str | None = None
    address_specification: str | None = None
    district: str | None = None


class Debtor(DomainModel):
    company: str = Field(min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    alias: str = Field(min_length=1)
    billing_address: Address
    delivery_address: Address | None = None


class Payment(DomainModel):
    method: str = Field(min_length=1)
    status: Literal["PAID", "UNPAID"]
    payment_date: date | None = None


class OrderItem(DomainModel):
    sku: str = Field(min_length=1)
    description: str = Field(min_length=1)
    quantity: Decimal = Field(ge=Decimal(0))
    unit_net: Decimal = Field(ge=Decimal(0))
    vat_percent: Decimal = Field(ge=Decimal(0), le=Decimal(100))
    discount_percent: Decimal = Field(ge=Decimal(0), le=Decimal(100))
    source_total: Decimal = Field(ge=Decimal(0))


class OrderTotals(DomainModel):
    net: Decimal = Field(ge=Decimal(0))
    vat: Decimal = Field(ge=Decimal(0))
    gross: Decimal = Field(ge=Decimal(0))
    discount_percent: Decimal | None = Field(
        default=None,
        ge=Decimal(0),
        le=Decimal(100),
    )
    shipping: Decimal | None = Field(default=None, ge=Decimal(0))


class OrderInput(DomainModel):
    order_date: date
    external_reference: str = Field(min_length=1)
    debtor: Debtor
    payment: Payment
    items: list[OrderItem] = Field(min_length=1)
    totals: OrderTotals
