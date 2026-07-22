#!/usr/bin/env python3
"""
Cipher Telegram Bot — tgbot/bot.py

私聊界面，支持文字/图片/语音。
文字通过 Cipher 管线处理，图片用 DeepSeek VL / OCR，语音用 whisper + edge-tts。
"""

import asyncio, io, os, sys, json, logging
import tempfile, traceback, base64, urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TOKEN, ALLOWED_USER_IDS, WORKDIR
from routing.entry import handle_core

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cipher_bot")

WHISPER_MODEL: Optional[object] = None
LAST_RESPONSE: dict = {}


def _check_user(update: Update) -> bool:
    uid = update.effective_user.id
    if ALLOWED_USER_IDS is not None and uid not in ALLOWED_USER_IDS:
        return False
    return True


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        await update.message.reply_text("未授权")
        return
    await update.message.reply_text(
        "Cipher Telegram Bot\n\n"
        "\u2022 发送文字 \u2192 Cipher 回答\n"
        "\u2022 发送图片 \u2192 识别内容后回答\n"
        "\u2022 发送语音 \u2192 转文字后回答\n"
        "\u2022 回复任意消息并说 /du 可以朗读"
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    text = update.message.text.strip()
    if not text:
        return
    await _process_and_reply(update, text)


async def handle_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    caption = update.message.caption or ""
    photo = update.message.photo[-1]
    file = await photo.get_file()
    raw = await file.download_as_bytearray()
    img_bytes = bytes(raw)

    description = _vision_describe(img_bytes) or _ocr_image(img_bytes)
    combined = f"[图片] {description}" if not caption else f"[图片] {caption}\n{description}"
    await _process_and_reply(update, combined)


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    voice = update.message.voice
    file = await voice.get_file()
    raw = await file.download_as_bytearray()
    ogg_bytes = bytes(raw)

    text = _transcribe(ogg_bytes) or "（语音未能识别）"
    logger.info("voice->text: %s", text)
    await _process_and_reply(update, text)


async def handle_read_aloud(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    uid = update.effective_user.id
    text = LAST_RESPONSE.get(uid)
    if not text:
        await update.message.reply_text("没有可朗读的回复")
        return
    audio = await _tts(text)
    if audio:
        await update.message.reply_voice(audio)
    else:
        await update.message.reply_text("语音生成失败")


async def _process_and_reply(update: Update, text: str):
    uid = update.effective_user.id
    try:
        reply = handle_core(text)
        if not reply or reply.strip() == "":
            reply = "（无回复）"
    except Exception as e:
        logger.error("handle_core error: %s\n%s", e, traceback.format_exc())
        reply = f"处理出错：{e}"

    LAST_RESPONSE[uid] = reply
    await update.message.reply_text(reply, disable_web_page_preview=True)


def _vision_describe(image_bytes: bytes) -> Optional[str]:
    try:
        from core.llm_client import _resolve_config
        url, key, model = _resolve_config()
        b64 = base64.b64encode(image_bytes).decode()
        body = json.dumps({
            "model": "deepseek-vl2",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "详细描述这张图片中的内容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 512,
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        req = urllib.request.Request(url.replace("/chat/completions", "/chat/completions"),
                                     data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("vision API failed: %s", e)
        return None


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


def _transcribe(ogg_bytes: bytes) -> Optional[str]:
    global WHISPER_MODEL
    try:
        if WHISPER_MODEL is None:
            import whisper
            WHISPER_MODEL = whisper.load_model("tiny")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(ogg_bytes)
            tmp = f.name
        try:
            import whisper
            audio = whisper.load_audio(tmp)
            audio = whisper.pad_or_trim(audio)
            result = WHISPER_MODEL.transcribe(audio, language="zh")
            return result.get("text", "").strip()
        finally:
            os.unlink(tmp)
    except Exception as e:
        logger.warning("whisper failed: %s", e)
        return None


async def _tts(text: str) -> Optional[bytes]:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        return data if data else None
    except Exception as e:
        logger.warning("TTS failed: %s", e)
        return None


def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN \u672a\u8bbe\u7f6e")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("du", handle_read_aloud))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Cipher Telegram Bot \u542f\u52a8")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
