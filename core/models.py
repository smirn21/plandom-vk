"""Доменные модели планировки."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProjectType(str, Enum):
    APARTMENT = "apartment"
    HOUSE = "house"
    SINGLE_ROOM = "single_room"


class RoomType(str, Enum):
    LIVING = "living"
    BEDROOM = "bedroom"
    KITCHEN = "kitchen"
    BATH = "bath"
    HALL = "hall"
    OFFICE = "office"
    KIDS = "kids"
    OTHER = "other"


@dataclass
class RoomSpec:
    name: str
    room_type: RoomType
    width_m: float | None = None
    length_m: float | None = None
    area_m2: float | None = None
    doors: list[dict[str, Any]] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectBrief:
    """Ввод пользователя перед генерацией."""
    project_type: ProjectType
    total_area_m2: float | None
    rooms: list[RoomSpec] = field(default_factory=list)
    style: str = "scandinavian"
    style_notes: str = ""
    budget_tier: str = "medium"  # economy | medium | premium
    floors: int = 1
    notes: str = ""
    ceiling_height_m: float | None = None
    openings_notes: str = ""
    wet_zones: str = ""
    furniture_wishes: str = ""
    blueprint_estimated: bool = False
    input_mode: str = "manual"  # manual | blueprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_type": self.project_type.value,
            "total_area_m2": self.total_area_m2,
            "rooms": [
                {
                    "name": r.name,
                    "room_type": r.room_type.value,
                    "width_m": r.width_m,
                    "length_m": r.length_m,
                    "area_m2": r.area_m2,
                    "doors": r.doors,
                    "windows": r.windows,
                }
                for r in self.rooms
            ],
            "style": self.style,
            "style_notes": self.style_notes,
            "budget_tier": self.budget_tier,
            "floors": self.floors,
            "notes": self.notes,
            "ceiling_height_m": self.ceiling_height_m,
            "openings_notes": self.openings_notes,
            "wet_zones": self.wet_zones,
            "furniture_wishes": self.furniture_wishes,
            "blueprint_estimated": self.blueprint_estimated,
            "input_mode": self.input_mode,
        }
