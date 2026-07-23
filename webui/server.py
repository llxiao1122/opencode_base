import sys, json, logging
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills"))
import platform as _py_platform

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, PlainTextResponse
import uvicorn
import asyncio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cipher_web")

ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = ROOT / "state" / "tasks.json"
TEAM_PATH = ROOT / "state" / "tasks_team.json"

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

def _load_team():
    if not TEAM_PATH.exists():
        return []
    try:
        return json.loads(TEAM_PATH.read_text("utf-8"))
    except Exception:
        return []

def _save_team(data):
    TEAM_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

@app.get("/api/tasks")
def list_tasks(filter: str = "", owner: str = ""):
    all_tasks = _load()
    active = [t for t in all_tasks if t.get("type") == "task" and t.get("status") in ("active", "in_progress")]
    completed = [t for t in all_tasks if t.get("type") == "task" and t.get("status") == "completed"]

    today = datetime.now().date()

    if filter == "today":
        active = [t for t in active if t.get("deadline") and t["deadline"].startswith(today.isoformat())]
    elif filter == "tomorrow":
        from datetime import timedelta
        tom = today + timedelta(days=1)
        active = [t for t in active if t.get("deadline") and t["deadline"].startswith(tom.isoformat())]

    def _owner_match(t, name):
        o = t.get("owner", "")
        if isinstance(o, dict):
            return o.get("name", "") == name
        return o == name

    def _priority_val(t):
        p = t.get("priority", "medium")
        if isinstance(p, dict):
            p = p.get("value", "medium")
        return PRIORITY_ORDER.get(p, 3)

    def _deadline_val(t):
        dl = t.get("deadline")
        return dl if dl else "9999"

    if owner:
        active = [t for t in active if _owner_match(t, owner)]
        completed = [t for t in completed if _owner_match(t, owner)]

    active.sort(key=lambda t: (_priority_val(t), _deadline_val(t)))
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
            team = _load_team()
            changed = False
            for st in team:
                if st.get("parent_id") == task_id and st.get("status") == "active":
                    st["status"] = "completed"
                    st["completed_at"] = datetime.now().isoformat(timespec="seconds")
                    changed = True
            if changed:
                _save_team(team)
            logger.info("task completed (cascade): %s", task_id)
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

@app.get("/api/team-tasks")
def list_team_tasks(owner: str = "", parent_id: str = "", status: str = ""):
    all_tasks = _load_team()
    if owner:
        all_tasks = [t for t in all_tasks if t.get("owner") == owner]
    if parent_id:
        all_tasks = [t for t in all_tasks if t.get("parent_id") == parent_id]
    if status:
        all_tasks = [t for t in all_tasks if t.get("status") == status]
    return all_tasks

@app.post("/api/team-tasks/{task_id}/complete")
def complete_team_task(task_id: str):
    data = _load_team()
    for t in data:
        if t.get("id") == task_id and t.get("status") == "active":
            t["status"] = "completed"
            t["completed_at"] = datetime.now().isoformat(timespec="seconds")
            _save_team(data)
            from skills.memory.observation_store import write as obs_write
            obs_write(
                f"{t.get('owner', '')} 完成了 {t.get('title', '')}（父任务: {t.get('parent_title', '')}）",
                source="team_task_complete",
                obs_type="task_completion",
                layer="rule",
                confidence=0.9
            )
            logger.info("team task completed: %s", task_id)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

@app.post("/api/team-tasks/{task_id}/reopen")
def reopen_team_task(task_id: str):
    data = _load_team()
    for t in data:
        if t.get("id") == task_id and t.get("status") == "completed":
            t["status"] = "active"
            t["completed_at"] = None
            _save_team(data)
            logger.info("team task reopened: %s", task_id)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

@app.get("/api/team-tasks/pending")
def pending_confirm():
    team = _load_team()
    parent_ids = set(t.get("parent_id") for t in team if t.get("parent_id"))
    parents = _load()
    parent_map = {p.get("id"): p for p in parents if p.get("type") == "task"}
    result = []
    for pid in parent_ids:
        subs = [t for t in team if t.get("parent_id") == pid]
        all_done = all(s.get("status") == "completed" for s in subs)
        if not all_done:
            continue
        parent = parent_map.get(pid)
        if parent is None:
            continue
        if parent.get("team_confirmed_at"):
            continue
        result.append({
            "parent_id": pid,
            "parent_title": parent.get("title", ""),
            "parent_priority": parent.get("priority", "medium"),
            "parent_deadline": parent.get("deadline"),
            "total": len(subs),
            "completed_count": len(subs),
        })
    return result

@app.post("/api/team-tasks/{parent_id}/confirm")
def confirm_parent_task(parent_id: str):
    data = _load()
    for t in data:
        if t.get("id") == parent_id and t.get("type") == "task":
            t["team_confirmed_at"] = datetime.now().isoformat(timespec="seconds")
            _save(data)
            logger.info("parent task confirmed: %s", parent_id)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

@app.get("/api/team-members")
def list_team_members():
    idx_path = ROOT / "state" / "entity_index.json"
    if not idx_path.exists():
        return ["李林骁", "陈红洁", "杨梦卓", "苗笑天", "谭继衡", "张志斌"]
    try:
        data = json.loads(idx_path.read_text("utf-8"))
        return data.get("_meta", {}).get("team_members",
            ["李林骁", "陈红洁", "杨梦卓", "苗笑天", "谭继衡", "张志斌"])
    except Exception:
        return ["李林骁", "陈红洁", "杨梦卓", "苗笑天", "谭继衡", "张志斌"]

@app.post("/api/tasks/{task_id}/assign")
def assign_task(task_id: str, body: dict):
    executor = (body or {}).get("executor", "").strip()
    if not executor:
        return JSONResponse({"ok": False, "error": "no executor"}, status_code=400)
    tasks = _load()
    parent = None
    for t in tasks:
        if t.get("id") == task_id:
            parent = t
            break
    if not parent:
        return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
    team = _load_team()
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    sub_id = f"sub_{now}_{len(team)}"
    subtask = {
        "id": sub_id,
        "parent_id": task_id,
        "parent_title": parent.get("title", ""),
        "title": parent.get("title", ""),
        "owner": executor,
        "status": "active",
        "deadline": parent.get("deadline", ""),
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "completed_at": None,
    }
    team.append(subtask)
    _save_team(team)
    logger.info("task assigned: %s -> %s", task_id, executor)
    return {"ok": True, "id": sub_id}

@app.post("/api/message")
def handle_message(body: dict):
    msg = (body or {}).get("message", "").strip()
    if not msg:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    try:
        import subprocess
        entry_py = ROOT / "skills" / "routing" / "entry.py"
        result = subprocess.run(
            [sys.executable, str(entry_py), msg],
            capture_output=True, text=True, timeout=120,
            cwd=str(ROOT)
        )
        return {"ok": True, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/message/stream")
async def stream_message(body: dict):
    msg = (body or {}).get("message", "").strip()
    if not msg:
        return PlainTextResponse("error: empty message\n", status_code=400)
    entry_py = ROOT / "skills" / "routing" / "entry.py"
    async def generate():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(entry_py), msg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT)
        )
        async for line in proc.stdout:
            yield line.decode(errors="replace")
        async for line in proc.stderr:
            yield line.decode(errors="replace")
        await proc.wait()
    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/")
def index():
    html = (Path(__file__).parent / "index.html").read_text("utf-8")
    return HTMLResponse(html)

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8081
    uvicorn.run(app, host="0.0.0.0", port=port)
