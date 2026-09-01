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


@dataclass
class ProjectBrief:
    """Ввод пользователя перед генерацией."""
    project_type: ProjectType
    total_area_m2: float | None
    rooms: list[RoomSpec] = field(default_factory=list)
    style: str = "scandinavian"
    budget_tier: str = "medium"  # economy | medium | premium
    floors: int = 1
    notes: str = ""

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
                }
                for r in self.rooms
            ],
            "style": self.style,
            "budget_tier": self.budget_tier,
            "floors": self.floors,
            "notes": self.notes,
        }
