#!/usr/bin/env python3
"""Cipher 钉钉 Webhook 接收器 —— 接收钉钉消息 → skills.entry() → 回复。

启动:
  python scripts/dingtalk_receiver.py [--port=5000] [--host=0.0.0.0]

钉钉回调 URL 需配置为:
  http(s)://<host>:<port>/dingtalk/callback
"""

import json
import logging
import sys
import traceback
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dingtalk_receiver")


def _extract_text(payload: dict) -> str:
    """兼容多种钉钉回调格式，提取消息文本。"""
    # 格式 1: 自定义机器人回调 {content: {msgtype: {content: "..."}}}
    if "content" in payload:
        inner = payload["content"]
        if isinstance(inner, dict):
            for typ in ("text", "message"):
                if typ in inner and isinstance(inner[typ], dict):
                    return inner[typ].get("content", "")
    # 格式 2: 直接文本 {text: {content: "..."}}
    for key in ("text", "message"):
        if key in payload and isinstance(payload[key], dict):
            return payload[key].get("content", "")
    # 格式 3: msg 字段
    if "msg" in payload:
        return str(payload["msg"])
    return ""


def _extract_sender(payload: dict) -> str:
    """提取发送者昵称。"""
    return (payload.get("senderNick")
            or payload.get("senderName")
            or payload.get("sender_id")
            or "未知")


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/dingtalk/callback", methods=["POST"])
def dingtalk_callback():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        text = _extract_text(payload)
        sender = _extract_sender(payload)
        session_webhook = payload.get("sessionWebhook", "")

        if not text.strip():
            return jsonify({"msg": "ignored: empty message"}), 200

        logger.info("📩 钉钉消息: [%s] %s", sender, text[:80])

        # 调用 Cipher 入口
        import skills.entry
        result = skills.entry.handle_core(text)
        if not result:
            result = "[Cipher]\n已收到，但暂无回复内容。"

        # 截断过长的回复（钉钉 markdown 限制 ~20000 字符）
        reply = result.strip()
        if len(reply) > 5000:
            reply = reply[:5000] + "\n\n...（回复过长已截断）"

        # 有 sessionWebhook → 私聊回复；否则发群
        if session_webhook:
            _reply_via_webhook(session_webhook, reply)
        else:
            _reply_to_group(reply)

        return jsonify({"msg": "handled", "sender": sender, "len": len(reply)}), 200

    except Exception:
        logger.error("callback error:\n%s", traceback.format_exc())
        return jsonify({"msg": "internal error"}), 500


def _reply_via_webhook(webhook_url: str, text: str):
    """通过 sessionWebhook 回复（私聊/临时会话）。"""
    import urllib.request
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"title": "Cipher 回复", "text": text},
    }).encode()
    req = urllib.request.Request(webhook_url, data=payload,
                                  headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)
    logger.info("📤 已通过 sessionWebhook 回复")


def _reply_to_group(text: str):
    """通过机器人 webhook 回复到群。"""
    from skills.plugins.dingbot.send_msg import send_markdown
    send_markdown("Cipher 回复", text)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cipher DingTalk Receiver")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    logger.info("🚀 Cipher DingTalk Receiver 启动: %s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)
