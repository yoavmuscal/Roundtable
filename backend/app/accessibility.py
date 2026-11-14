"""Backend helpers for accessibility-facing alerts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class NameAlert:
    names: dict[str, list[str]] = field(default_factory=dict)  # person id -> aliases
    alerted_turns: set[str] = field(default_factory=set)

    def set_names(self, person_id: str, name: str, aliases: list[str] | None = None) -> None:
        values = [name, *(aliases or [])]
        self.names[person_id] = [value.strip() for value in values if value.strip()]

    def check_turn(self, turn_id: str, text: str) -> dict[str, object] | None:
        """Return one alert per turn when any enrolled name is mentioned."""
        if turn_id in self.alerted_turns:
            return None
        for person_id, aliases in self.names.items():
            for alias in aliases:
                pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
                if pattern.search(text):
                    self.alerted_turns.add(turn_id)
                    return {"turnId": turn_id, "personId": person_id, "matchedName": alias}
        return None
