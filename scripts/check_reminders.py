"""Cron entry: single-shot task deadline reminder check."""
import logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
from skills.trigger.daemon import ProactiveDaemon
ProactiveDaemon()._check_impending_tasks()
