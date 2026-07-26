import sys
from pathlib import Path

_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_SKILLS: Path = _ROOT / "skills"

_added: bool = False


def ensure_paths():
    global _added
    if _added:
        return
    for p in [str(_ROOT), str(_SKILLS)]:
        if p not in sys.path:
            sys.path.insert(0, p)
    _added = True


def root() -> Path:
    return _ROOT


def skills_dir() -> Path:
    return _SKILLS


def state_dir() -> Path:
    return _ROOT / "data" / "state"


def memory_dir() -> Path:
    return _ROOT / "data" / "memory"
