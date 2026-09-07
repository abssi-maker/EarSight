"""
Shared models used across all EarSight agents.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Word:
    word: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class Transcript:
    """Word-level transcript with timing."""
    words: list[Word]
    language: str = "en"
    full_text: str = ""

    @property
    def duration(self) -> float:
        if not self.words:
            return 0.0
        return self.words[-1].end

    def dialogue_spans(self) -> list[dict]:
        """Return all word spans as collision-guard input."""
        return [{"start": w.start, "end": w.end, "word": w.word} for w in self.words]


@dataclass
class Gap:
    """A silence gap between dialogue words."""
    gap_id: str
    start: float   # seconds
    end: float     # seconds
    duration: float  # seconds = end - start
    frame_path: Optional[str] = None  # path to representative frame image
    preceding_context: str = ""  # dialogue immediately before
    following_context: str = ""  # dialogue immediately after


@dataclass
class Cue:
    """A timed narration cue."""
    cue_id: str
    start: float   # seconds
    end: float     # seconds
    text: Optional[str]  # None = skipped
    word_count: int = 0
    gap_id: str = ""
    skip_reason: Optional[str] = None  # "budget" | "salience" | "redundant" | None
    audio_path: Optional[str] = None   # path to synthesised audio clip


@dataclass
class Job:
    """Pipeline job state."""
    job_id: str
    video_path: str
    status: str = "queued"
    transcript: Optional[Transcript] = None
    gaps: list[Gap] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    result_video_path: Optional[str] = None
    result_vtt_path: Optional[str] = None
    error: Optional[str] = None
