"""
Word-budget enforcement.

The hard rule: floor(gap_duration_seconds × 2.75) words.
A cue exceeding its budget must be dropped, never truncated.
"""

import math


WORDS_PER_SECOND = 2.75


def word_budget(gap_seconds: float) -> int:
    """Return the maximum number of words that fit in a silence gap."""
    return math.floor(gap_seconds * WORDS_PER_SECOND)


def count_words(text: str) -> int:
    return len(text.split())


def fits_budget(text: str, gap_seconds: float) -> bool:
    """Return True if text fits within the word budget for this gap."""
    return count_words(text) <= word_budget(gap_seconds)


def assert_fits(text: str, gap_seconds: float, gap_id: str = "") -> None:
    """
    Raise BudgetExceededError if text exceeds word budget.
    Called before any cue is committed to output.
    """
    budget = word_budget(gap_seconds)
    actual = count_words(text)
    if actual > budget:
        label = f" (gap {gap_id})" if gap_id else ""
        raise BudgetExceededError(
            f"Cue{label} exceeds budget: {actual} words > {budget} allowed "
            f"({gap_seconds:.2f}s gap). Text: {text!r}"
        )


class BudgetExceededError(ValueError):
    """Raised when cue copy exceeds the word budget for its gap."""
