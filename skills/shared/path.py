import sys
from pathlib import Path

def _find_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(10):
        if (p / "skills").is_dir():
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent.parent

_ROOT: Path = _find_root()
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
