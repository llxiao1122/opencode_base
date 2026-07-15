#!/usr/bin/env python3
"""
TG ←→ Agent CLI 桥接

TG 消息通过 agent_cli.py 处理，按 AGENTS.md 路由执行。
使用 DeepSeek API + 轻量 Python 路由器，内存 ~50MB。
"""

import subprocess, requests, time, datetime, os, sys, atexit, fcntl

from config import TOKEN, CHAT_ID, PROXY

ALLOWED_CHAT_ID = CHAT_ID.strip() if CHAT_ID.strip() else None

PROJECT_ROOT = "/home/admin/opencode"

PROXIES = {"http": PROXY, "https": PROXY}
BASE = os.path.dirname(os.path.abspath(__file__))
OFFSET_FILE = os.path.join(BASE, "offset.txt")
PID_FILE = os.path.join(BASE, "bot.pid")

# ── PID 文件锁 ──────────────────────────────────────

_lock_fd = None

def _acquire_lock() -> bool:
    global _lock_fd
    try:
        _lock_fd = open(PID_FILE, "a+")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.seek(0); _lock_fd.truncate()
        _lock_fd.write(str(os.getpid())); _lock_fd.flush()
        return True
    except OSError:
        if _lock_fd: _lock_fd.close(); _lock_fd = None
        return False

def _release_lock():
    global _lock_fd
    if _lock_fd:
        try: fcntl.flock(_lock_fd, fcntl.LOCK_UN); _lock_fd.close()
        except: pass
        finally: _lock_fd = None
    try: os.remove(PID_FILE)
    except: pass

atexit.register(_release_lock)

# ── 日志 ───────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)

# ── TG API ─────────────────────────────────────────

def tg_get_updates(offset: int) -> list:
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                         params={"offset": offset, "timeout": 30},
                         proxies=PROXIES, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        log(f"getUpdates 错误: {e}")
        return []

def tg_send(chat_id: str, text: str) -> bool:
    # TG 单条上限 4096 字符，超长分段
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                             params={"chat_id": chat_id, "text": chunk},
                             proxies=PROXIES, timeout=15)
            if not r.json().get("ok"):
                log(f"sendMessage 失败: {r.json().get('description', '?')}")
                return False
        except Exception as e:
            log(f"sendMessage 错误: {e}")
            return False
    return True

def _save_offset(offset: int):
    try:
        with open(OFFSET_FILE, "w") as f: f.write(str(offset))
    except Exception as e:
        log(f"保存 offset 失败: {e}")


# ── 快速回复 ──────────────────────────────────────

_SIMPLE = {
    "你好": "你好！", "hi": "hi，我在", "hello": "Hello，我在",
    "hey": "Hey，在的", "嗨": "嗨，我在", "在吗": "在的，你说",
    "在不在": "在的", "好了吗": "好了", "嗯": "嗯？你说",
    "好的": "好的", "ok": "OK", "okk": "OK", "好": "好",
    "行": "行", "可以": "可以", "没问题": "没问题",
    "知道了": "好的", "明白": "明白", "收到": "收到",
    "谢谢": "不客气", "早": "早！", "晚安": "晚安！",
    "1": "👌", "👍": "👍",
}

# ── 核心 ──────────────────────────────────────────

def _ask(text: str) -> str:
    try:
        agent_cli = os.path.join(PROJECT_ROOT, "agent_cli.py")
        cmd = ["python3", agent_cli, text, "--session", "telegram"]
        r = subprocess.run(cmd,
            capture_output=True, text=True, timeout=180, cwd=PROJECT_ROOT,
        )
        if r.returncode != 0:
            return f"[Agent CLI 错误: {r.stderr.strip()[:200]}]"
        return r.stdout.strip() or "[无回复]"
    except subprocess.TimeoutExpired:
        return "[超时]"
    except Exception as e:
        return f"[异常: {str(e)[:100]}]"

def handle_message(text: str) -> str:
    t = text.strip().lower()
    if t in _SIMPLE:
        return _SIMPLE[t]

    log(f"→ {text[:50]}...")
    reply = _ask(text)
    log(f"← {len(reply)} 字")
    return reply

# ── 主循环 ────────────────────────────────────────

def main():
    if not _acquire_lock():
        print("❌ TG Bridge 已在运行中。", flush=True)
        sys.exit(1)

    log(f"=== TG↔Opencode 启动 ===")

    offset = 0
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            try: offset = int(f.read().strip())
            except: pass

    log(f"监听 offset={offset}")
    errors = 0

    while True:
        try:
            updates = tg_get_updates(offset)
            errors = 0
            for up in updates:
                offset = up["update_id"] + 1
                msg = up.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
                    continue
                text = msg.get("text", "")
                if text:
                    reply = handle_message(text)
                    tg_send(chat_id, reply)
                _save_offset(offset)
        except KeyboardInterrupt:
            log("退出"); break
        except Exception as e:
            errors += 1
            delay = min(2 ** errors, 60)
            log(f"异常 #{errors}: {e}，{delay}s 后重试")
            time.sleep(delay)

if __name__ == "__main__":
    main()
