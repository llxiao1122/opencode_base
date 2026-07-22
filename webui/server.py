import sys, json, logging
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills"))
import platform as _py_platform

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cipher_web")

ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = ROOT / "state" / "tasks.json"

app = FastAPI(title="Cipher Tasks")

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

def _load():
    if not TASKS_PATH.exists():
        return []
    try:
        return json.loads(TASKS_PATH.read_text("utf-8"))
    except Exception:
        return []

def _save(data):
    TASKS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

@app.get("/api/tasks")
def list_tasks(filter: str = "", owner: str = ""):
    all_tasks = _load()
    active = [t for t in all_tasks if t.get("type") == "task" and t.get("status") == "active"]
    completed = [t for t in all_tasks if t.get("type") == "task" and t.get("status") == "completed"]

    today = datetime.now().date()

    if filter == "today":
        active = [t for t in active if t.get("deadline") and t["deadline"].startswith(today.isoformat())]
    elif filter == "tomorrow":
        from datetime import timedelta
        tom = today + timedelta(days=1)
        active = [t for t in active if t.get("deadline") and t["deadline"].startswith(tom.isoformat())]

    if owner:
        active = [t for t in active if t.get("owner") == owner]
        completed = [t for t in completed if t.get("owner") == owner]

    active.sort(key=lambda t: (PRIORITY_ORDER.get(t.get("priority", "medium"), 3), t.get("deadline", "9999") if t.get("deadline") else "9999"))
    completed.sort(key=lambda t: t.get("completed_at", ""), reverse=True)

    return {"active": active, "completed": completed}

@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: str):
    data = _load()
    for t in data:
        if t.get("id") == task_id and t.get("type") == "task" and t.get("status") == "active":
            t["status"] = "completed"
            t["completed_at"] = datetime.now().isoformat(timespec="seconds")
            _save(data)
            logger.info("task completed: %s", task_id)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

@app.post("/api/tasks/{task_id}/reopen")
def reopen_task(task_id: str):
    data = _load()
    for t in data:
        if t.get("id") == task_id and t.get("type") == "task" and t.get("status") == "completed":
            t["status"] = "active"
            t["completed_at"] = None
            _save(data)
            logger.info("task reopened: %s", task_id)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

@app.get("/")
def index():
    html = (Path(__file__).parent / "index.html").read_text("utf-8")
    return HTMLResponse(html)

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8081
    uvicorn.run(app, host="0.0.0.0", port=port)
