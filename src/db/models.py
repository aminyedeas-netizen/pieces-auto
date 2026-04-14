"""Data models for Pieces Auto TN."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MISS = "miss"


@dataclass
class Vehicle:
    """Vehicle from PiecesAuto24, stored in vehicles table."""
    id: int | None = None
    brand: str = ""
    model: str = ""
    chassis_code: str | None = None
    displacement: str | None = None
    power_hp: int | None = None
    fuel: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    engine_code: str | None = None
    pa24_full_name: str = ""


@dataclass
class VehicleInfo:
    """Decoded vehicle info from VIN or user selection."""
    make: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    fuel: str | None = None
    vin: str | None = None
    vehicle_id: int | None = None
    pa24_full_name: str | None = None
    confidence: Confidence = Confidence.MISS
    explanation: list[str] = field(default_factory=list)


@dataclass
class PartRequest:
    """Parsed customer request."""
    vehicle: VehicleInfo | None = None
    part_name: str | None = None
    part_name_raw: str = ""
    direct_reference: str | None = None
    vin: str | None = None
    vehicle_hint: str | None = None


@dataclass
class StoredReference:
    """Part reference from DB."""
    id: int | None = None
    vehicle_id: int | None = None
    part_name: str = ""
    brand: str = ""
    reference: str = ""
    is_oe: bool = False
    price_eur: float | None = None
    source: str = "piecesauto24"


@dataclass
class CDGResult:
    """Result from CDG wholesaler search."""
    reference: str = ""
    brand: str = ""
    description: str = ""
    price: float | None = None
    available: bool = False
    quantity: int | None = None
