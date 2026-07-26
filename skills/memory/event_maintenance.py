"""
event_maintenance.py — Periodic Event Maintenance
Marks active/detected events as expired when past deadline with no activity.
Manual or cron-driven; not auto-hooked into message pipeline.
"""

import sys
from datetime import datetime

from skills.shared.path import ensure_paths
ensure_paths()

from memory.detect import change_status, load_index


def run_maintenance():
    index = load_index()
    today = datetime.now().strftime("%Y-%m-%d")

    expired = []
    for e in index.get("events", []):
        if e["status"] not in ("active", "detected"):
            continue
        deadline = e.get("deadline", "")
        if deadline and deadline < today:
            change_status(e["id"], "expired")
            expired.append(e["id"])

    return expired


def main():
    result = run_maintenance()
    if result:
        for eid in result:
            print(f"expired: {eid}")
    else:
        print("no expired events")


if __name__ == "__main__":
    main()
