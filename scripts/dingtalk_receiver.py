#!/usr/bin/env python3
"""Cipher 独立服务 —— 网页聊天 + 钉钉 Webhook 双通道。

启动:
  python scripts/dingtalk_receiver.py [--port=5000] [--host=0.0.0.0]

网页聊天：浏览器打开 http(s)://<host>:<port>/
钉钉回调：POST http(s)://<host>:<port>/dingtalk/callback
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

from flask import Flask, request, jsonify, Response, stream_with_context

app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dingtalk_receiver")

CHAT_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Cipher</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;height:100dvh;display:flex;flex-direction:column}
.header{background:#16213e;padding:12px 16px;font-size:16px;font-weight:600;border-bottom:1px solid #0f3460;display:flex;align-items:center;gap:8px}
.header .dot{width:8px;height:8px;background:#4ecca3;border-radius:50%}
.messages{flex:1;overflow-y:auto;padding:12px}
.msg{margin-bottom:12px;max-width:90%;line-height:1.5}
.msg.user{text-align:right;margin-left:auto}
.msg.user .bubble{background:#0f3460;padding:10px 14px;border-radius:16px 4px 16px 16px;display:inline-block;text-align:left;max-width:100%;word-break:break-word}
.msg.cipher .bubble{background:#16213e;padding:10px 14px;border-radius:4px 16px 16px 16px;display:inline-block;max-width:100%;word-break:break-word}
.msg.cipher .bubble pre{background:#1a1a2e;padding:8px;border-radius:4px;overflow-x:auto;font-size:13px;margin:4px 0;white-space:pre-wrap}
.msg .meta{font-size:11px;color:#888;margin:4px 8px 0}
.input-area{display:flex;padding:10px;gap:8px;background:#16213e;border-top:1px solid #0f3460}
.input-area input{flex:1;padding:10px 14px;border:1px solid #0f3460;border-radius:20px;background:#1a1a2e;color:#e0e0e0;font-size:14px;outline:none}
.input-area input:focus{border-color:#4ecca3}
.input-area button{background:#4ecca3;color:#1a1a2e;border:none;padding:10px 20px;border-radius:20px;font-size:14px;font-weight:600;cursor:pointer}
.input-area button:disabled{opacity:.4}
</style>
</head>
<body>
<div class="header"><span class="dot"></span>Cipher</div>
<div class="messages" id="msgs">
<div class="msg cipher"><div class="bubble">主人，Cipher 在线。<br>可以直接问工作安排、查员工、查制度。</div><div class="meta">Cipher · 刚刚</div></div>
</div>
<div class="input-area">
<input id="inp" placeholder="输入消息..." autofocus onkeydown="if(event.key==='Enter')send()">
<button id="btn" onclick="send()">发送</button>
</div>
<script>
let streamBubble=null;
async function send(){
  const inp=document.getElementById('inp'),btn=document.getElementById('btn');
  const text=inp.value.trim();if(!text)return;
  inp.disabled=btn.disabled=true;
  append('user',text);
  inp.value='';
  try{
    const r=await fetch('/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    if(!r.ok){append('cipher','请求失败: '+r.status);inp.disabled=btn.disabled=false;inp.focus();return;}
    streamBubble=createStreamBubble();
    const reader=r.body.getReader();const decoder=new TextDecoder();
    while(true){
      const{value,done}=await reader.read();
      if(done)break;
      const chunk=decoder.decode(value,{stream:true});
      streamBubble.innerHTML+=chunk.replace(/\\n/g,'<br>');
      document.getElementById('msgs').scrollTop=document.getElementById('msgs').scrollHeight;
    }
    finishStreamBubble();
    streamBubble=null;
  }catch(e){append('cipher','出错了: '+e);finishStreamBubble();streamBubble=null;}
  inp.disabled=btn.disabled=false;inp.focus();
}
function createStreamBubble(){
  const d=document.getElementById('msgs');
  const el=document.createElement('div');el.className='msg cipher';
  const bubble=document.createElement('div');bubble.className='bubble';
  const meta=document.createElement('div');meta.className='meta';meta.textContent='Cipher · 刚刚';
  el.appendChild(bubble);el.appendChild(meta);
  d.appendChild(el);d.scrollTop=d.scrollHeight;
  return bubble;
}
function finishStreamBubble(){
  if(!streamBubble)return;
  if(!streamBubble.textContent.trim())streamBubble.textContent='Cipher 暂无回复';
}
function append(role,text){
  const d=document.getElementById('msgs');
  const el=document.createElement('div');el.className='msg '+role;
  el.innerHTML='<div class="bubble">'+text.replace(/\\n/g,'<br>')+'</div><div class="meta">'+(role==='cipher'?'Cipher':'主人')+' · 刚刚</div>';
  d.appendChild(el);d.scrollTop=d.scrollHeight;
}
</script>
</body>
</html>"""


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


@app.route("/", methods=["GET"])
def web_chat():
    return CHAT_PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/chat", methods=["POST"])
def chat_api():
    try:
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or data.get("message") or "").strip()
        if not text:
            return jsonify({"reply": "消息不能为空"}), 400

        logger.info("💬 网页消息: %s", text[:80])

        import skills.entry
        result = skills.entry.handle_core(text)
        reply = (result or "[Cipher]\n已收到，但暂无回复内容。").strip()
        if len(reply) > 8000:
            reply = reply[:8000] + "\n\n...（回复过长已截断）"

        return jsonify({"reply": reply}), 200
    except Exception:
        logger.error("chat error:\n%s", traceback.format_exc())
        return jsonify({"reply": "处理出错，请重试"}), 500


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json(force=True, silent=True) or {}
    sender = data.get("sender", "web")
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400

    logger.info("💬 网页流式: [%s] %s", sender, text[:80])

    def generate():
        from skills.agent.engine import run_stream
        from skills.memory.conversation import add as conv_add
        full = ""
        try:
            for chunk in run_stream(sender, text):
                full += chunk
                yield chunk
        except Exception:
            logger.error("stream error:\n%s", traceback.format_exc())
            err_msg = "\n[Cipher]\n处理出错，请重试。"
            full += err_msg
            yield err_msg
        if full:
            try:
                conv_add(sender, "user", text)
                conv_add(sender, "assistant", full)
            except Exception:
                pass

    return Response(stream_with_context(generate()), mimetype="text/plain; charset=utf-8")


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
