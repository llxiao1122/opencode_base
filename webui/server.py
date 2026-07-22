import sys, os, json, io, base64, tempfile, logging, asyncio
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "skills"))
import platform as _py_platform  # prevent shadowing

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from routing.entry import handle_core

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cipher_web")

ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = ROOT / "state" / "tasks.json"
KNOWLEDGE_PATH = ROOT / "Knowledge" / "00-日常工作指引.md"

app = FastAPI(title="Cipher Web")

@app.get("/tasks")
def get_tasks():
    if not TASKS_PATH.exists():
        return []
    try:
        tasks = json.loads(TASKS_PATH.read_text("utf-8"))
    except Exception:
        return []
    active = [t for t in tasks if t.get("type") == "task" and t.get("status") == "active"]
    active.sort(key=lambda t: (
        {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "medium"), 3),
        t.get("deadline", "9999") if t.get("deadline") else "9999"
    ))
    return active

@app.get("/knowledge")
def get_knowledge():
    if not KNOWLEDGE_PATH.exists():
        return ""
    return KNOWLEDGE_PATH.read_text("utf-8")

@app.post("/message")
async def post_message(text: str = Form(...)):
    try:
        reply = handle_core(text)
        return {"reply": reply or "（无回复）"}
    except Exception as e:
        logger.error("handle_core error: %s", e, exc_info=True)
        return {"reply": f"处理出错：{e}"}

@app.post("/upload/image")
async def upload_image(file: UploadFile = File(...), caption: str = Form("")):
    raw = await file.read()
    description = _ocr_image(raw)
    combined = f"[图片] {description}" if not caption else f"[图片] {caption}\n{description}"
    try:
        reply = handle_core(combined)
        return {"text": combined, "reply": reply}
    except Exception as e:
        return {"text": combined, "reply": f"处理出错：{e}"}

@app.post("/upload/voice")
async def upload_voice(file: UploadFile = File(...)):
    raw = await file.read()
    text = _transcribe(raw) or "（语音未能识别）"
    try:
        reply = handle_core(text)
        return {"text": text, "reply": reply}
    except Exception as e:
        return {"text": text, "reply": f"处理出错：{e}"}

def _ocr_image(image_bytes: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
        return text or "（图片中未识别到文字）"
    except Exception as e:
        logger.warning("OCR failed: %s", e)
        return "（OCR 不可用）"

def _transcribe(ogg_bytes: bytes) -> str:
    try:
        import whisper
        model = whisper.load_model("tiny")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(ogg_bytes)
            tmp = f.name
        try:
            audio = whisper.load_audio(tmp)
            audio = whisper.pad_or_trim(audio)
            result = model.transcribe(audio, language="zh")
            return result.get("text", "").strip()
        finally:
            os.unlink(tmp)
    except Exception as e:
        logger.warning("whisper failed: %s", e)
        return ""

@app.get("/")
def index():
    html = (Path(__file__).parent / "index.html").read_text("utf-8")
    return HTMLResponse(html)

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8081
    uvicorn.run(app, host="0.0.0.0", port=port)
