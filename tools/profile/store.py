"""
profile/store.py — Profile persistence (lightweight compat layer).

Now profiles are computed in real-time by retriever.py.
This module provides backward-compatible get_profile().
"""

from profile.retriever import get_person_context


def get_profile(name: str) -> dict:
    """Get a person's profile. Computed in real-time from tasks + org_memory."""
    return get_person_context(name)


def load_all() -> dict:
    """Load all profiles (not supported — use retriever directly)."""
    return {}


def save_all(profiles: dict):
    """No-op — profiles are computed in real-time, not persisted."""
    pass
