"""
Collision guard.

THE ONE RULE THAT MUST NEVER BREAK:
No cue may overlap dialogue. Not by 100ms.

A CollisionError raised here means the cue never reaches output.
A silent gap is correct behaviour. Talking over a line is a defect.
"""

from dataclasses import dataclass
from typing import Sequence


COLLISION_TOLERANCE_MS = 0  # zero tolerance — any overlap is a defect


@dataclass
class TimeSpan:
    start: float  # seconds
    end: float    # seconds
    label: str = ""

    def overlaps(self, other: "TimeSpan") -> bool:
        """Return True if this span overlaps other (even by 1ms)."""
        return self.start < other.end and self.end > other.start


def assert_no_collision(
    cues: Sequence[dict],
    dialogue_spans: Sequence[dict],
) -> None:
    """
    Assert that no cue overlaps any dialogue span.

    Args:
        cues: list of dicts with 'start', 'end', 'text' keys (seconds)
        dialogue_spans: list of dicts with 'start', 'end' keys (seconds)

    Raises:
        CollisionError: if any cue overlaps any dialogue span.
    """
    dialogue = [
        TimeSpan(start=s["start"], end=s["end"], label=s.get("word", "dialogue"))
        for s in dialogue_spans
    ]

    for cue in cues:
        if cue.get("text") is None:
            continue  # skipped cues don't collide
        cue_span = TimeSpan(
            start=cue["start"],
            end=cue["end"],
            label=cue.get("text", "")[:40],
        )
        for d in dialogue:
            if cue_span.overlaps(d):
                raise CollisionError(
                    f"Cue [{cue_span.start:.3f}–{cue_span.end:.3f}s] "
                    f"overlaps dialogue [{d.start:.3f}–{d.end:.3f}s] "
                    f"word={d.label!r}. "
                    f"Cue text: {cue_span.label!r}"
                )


class CollisionError(ValueError):
    """
    Raised when a cue would overlap dialogue.
    This is the one hard constraint that must fail a build.
    """
