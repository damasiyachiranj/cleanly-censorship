"""Load word lists and build the final list for a run (ALGORITHM.md, section 1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

SEVERITIES = ("mild", "strong", "slur")

STRICTNESS = {
    "light": {"slur"},
    "moderate": {"strong", "slur"},
    "strict": {"mild", "strong", "slur"},
}

MODES = ("standard", "customized", "mylist")


@dataclass(frozen=True)
class Entry:
    word: str
    variants: tuple[str, ...] = field(default_factory=tuple)
    severity: str = "strong"
    source: str = "standard"  # "standard" or "user"

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.word, *self.variants)


def _entry_from_obj(obj, source: str) -> Entry:
    if isinstance(obj, str):
        return Entry(word=obj, severity="strong", source=source)
    severity = obj.get("severity", "strong")
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown severity {severity!r} for word {obj.get('word')!r}")
    return Entry(
        word=obj["word"],
        variants=tuple(obj.get("variants", [])),
        severity=severity,
        source=source,
    )


def load_standard(language: str = "en") -> list[Entry]:
    """Load the built-in Standard list for a language."""
    path = resources.files("cleanly") / "data" / f"standard_{language}.json"
    if not path.is_file():
        raise ValueError(f"No Standard list for language {language!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_entry_from_obj(e, "standard") for e in data["entries"]]


@dataclass
class UserList:
    remove: list[str] = field(default_factory=list)
    add: list[Entry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "UserList":
        """Load a user list: {"remove": ["word"], "add": ["word" or {entry}]}"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            remove=[w.lower() for w in data.get("remove", [])],
            add=[_entry_from_obj(e, "user") for e in data.get("add", [])],
        )


def build_list(
    standard: list[Entry],
    mode: str = "standard",
    strictness: str = "strict",
    user: UserList | None = None,
) -> list[Entry]:
    """Combine the Standard list and the user's list (ALGORITHM.md, section 1)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if strictness not in STRICTNESS:
        raise ValueError(f"strictness must be one of {tuple(STRICTNESS)}")
    user = user or UserList()
    allowed = STRICTNESS[strictness]
    removed = {w.lower() for w in user.remove}

    if mode == "standard":
        return [e for e in standard if e.severity in allowed]
    if mode == "customized":
        base = [e for e in standard if e.severity in allowed and e.word.lower() not in removed]
    else:  # mylist
        base = []
    return base + list(user.add)
