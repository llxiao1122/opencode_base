"""
Legacy compat wrapper — delegates to observation_store.
"""


def write_observation(topic: str, content: str):
    from memory.observation_store import write
    write(f"{topic}: {content}", source="manual", obs_type="note")


def load_observations(subject_type: str, subject_name: str) -> str:
    from memory.observation_store import read
    return read(subject_type, subject_name)
