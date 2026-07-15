#!/usr/bin/env python3
import sys, os, json, subprocess, datetime, argparse, requests

PROJECT_ROOT = "/home/admin/opencode"
MEMORY_DIR = os.path.join(PROJECT_ROOT, "memory")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
STATE_DIR = os.path.join(PROJECT_ROOT, "state")

CONFIG_PATH = os.path.expanduser("~/.config/opencode/opencode.jsonc")
try:
    with open(CONFIG_PATH) as f:
        _cfg = json.load(f)
    DEEPSEEK_API_KEY = _cfg["provider"]["deepseek"]["options"]["apiKey"]
except:
    DEEPSEEK_API_KEY = ""

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

MAX_HISTORY_ROUNDS = 5
MAX_CONTEXT_CHARS = 8000

_SIMPLE = {
    "你好": "你好！", "hi": "hi，我在", "hello": "Hello，我在",
    "hey": "Hey，在的", "嗨": "嗨，我在", "在吗": "在的，你说",
    "在不在": "在的", "好了吗": "好了", "嗯": "嗯？你说",
    "好的": "好的", "ok": "OK", "okk": "OK", "好": "好",
    "行": "行", "可以": "可以", "没问题": "没问题",
    "知道了": "好的", "明白": "明白", "收到": "收到",
    "谢谢": "不客气", "早": "早！", "晚安": "晚安！",
}

_SHORTCUTS = [
    (("安排", "待办", "排班", "完成", "清理"), "tools/task_manager/manage_tasks.py"),
    (("制度", "流程", "手册", "台账", "规范"), "tools/knowledge_router/query_knowledge.py"),
    (("团队", "领导", "分配", "汇报", "纪要"), "tools/state_analyzer/analyze_state.py"),
]


def read_file(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def append_file(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_tool(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=PROJECT_ROOT, timeout=timeout)
        out = r.stdout or ""
        err = r.stderr or ""
        return (out + "\n" + err).strip() if err else out.strip()
    except subprocess.TimeoutExpired:
        return "[超时]"
    except Exception as e:
        return f"[异常: {e}]"


def call_llm(messages, temperature=0.7):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
        "stream": False
    }
    try:
        r = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[LLM 错误: {e}]"


# ── History ──

def load_history(session_id):
    path = os.path.join(MEMORY_DIR, "sessions", f"session_{session_id}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"summary": "", "messages": []}


def save_history(session_id, data):
    os.makedirs(os.path.join(MEMORY_DIR, "sessions"), exist_ok=True)
    path = os.path.join(MEMORY_DIR, "sessions", f"session_{session_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def trim_history(history):
    msgs = history.get("messages", [])
    user_rounds = [m for m in msgs if m["role"] == "user"]
    if len(user_rounds) <= MAX_HISTORY_ROUNDS:
        return
    keep = MAX_HISTORY_ROUNDS * 2
    old = msgs[:-keep]
    history["messages"] = msgs[-keep:]
    old_summary = history.get("summary", "")
    new_parts = []
    for m in old:
        role = "用户" if m["role"] == "user" else "助手"
        new_parts.append(f"{role}: {m['content'][:100]}")
    new_text = " | ".join(new_parts)
    if old_summary:
        history["summary"] = f"{old_summary} ; {new_text[:200]}"
    else:
        history["summary"] = new_text[:300]


# ── Logs ──

def append_log(text):
    os.makedirs(LOGS_DIR, exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    ts = datetime.datetime.now().strftime("%H:%M")
    append_file(os.path.join(LOGS_DIR, f"{today}.log"), f"{today} {ts} {text}")
    _archive_logs()


def get_logs_summary():
    os.makedirs(LOGS_DIR, exist_ok=True)
    today = datetime.date.today()
    seen = set()
    entries = []
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        path = os.path.join(LOGS_DIR, f"{d.strftime('%Y-%m-%d')}.log")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and line not in seen:
                        seen.add(line)
                        text = line.split(" ", 2)[-1] if line.count(" ") >= 2 else line
                        entries.append(text[:60])
                        if len(entries) >= 5:
                            break
        if len(entries) >= 5:
            break
    return "近况: " + " | ".join(entries[:5]) if entries else ""


def _archive_logs():
    today = datetime.date.today()
    current_month = today.strftime("%Y-%m")
    for fname in os.listdir(LOGS_DIR):
        if not fname.endswith(".log") or fname.count("-") != 2:
            continue
        date_part = fname.replace(".log", "")
        try:
            file_date = datetime.datetime.strptime(date_part, "%Y-%m-%d").date()
        except:
            continue
        file_month = file_date.strftime("%Y-%m")
        if file_month >= current_month:
            continue
        daily_path = os.path.join(LOGS_DIR, fname)
        content = read_file(daily_path)
        if content:
            append_file(os.path.join(LOGS_DIR, f"{file_month}.log"), content.strip())
        os.remove(daily_path)


# ── Member ──

def _load_members():
    path = os.path.join(STATE_DIR, "_index.md")
    content = read_file(path)
    members = {}
    for line in content.split("\n"):
        if "→" not in line or line.strip().startswith("#"):
            continue
        parts = line.split("→")
        if len(parts) == 2:
            name = parts[0].strip()
            fpath = parts[1].strip()
            if fpath.startswith("members/"):
                members[name] = os.path.join(STATE_DIR, fpath)
    return members


def detect_member(text):
    members = _load_members()
    if not members:
        return None, None
    for name in sorted(members, key=len, reverse=True):
        if name in text:
            return name, members[name]
    return None, None


def get_member_context(filepath):
    return read_file(filepath)[:1000]


def update_member_portrait(name, content_tag):
    members = _load_members()
    filepath = members.get(name)
    if not filepath:
        return
    current = read_file(filepath)
    if not current:
        return
    base = content_tag
    tag = ""
    if "(" in base and base.endswith(")"):
        idx = base.rindex("(")
        tag = f" {base[idx+1:-1]}"
        base = base[:idx].strip()
    month_cn = datetime.date.today().strftime("%m月")
    entry = f"- {base}({tag.strip()} {month_cn})" if tag else f"- {base}({month_cn})"
    if entry in current:
        return
    eval_marker = "## 评价"
    eval_idx = current.find(eval_marker)
    if eval_idx >= 0:
        after = current[eval_idx + len(eval_marker):]
        next_sec = after.find("\n## ")
        if next_sec >= 0:
            ipos = eval_idx + len(eval_marker) + next_sec
            current = current[:ipos] + f"\n{entry}" + current[ipos:]
        else:
            current = current.rstrip() + f"\n{entry}\n"
    else:
        current = current.rstrip() + f"\n\n{eval_marker}\n{entry}\n"
    write_file(filepath, current)


# ── Record parsing & distribution ──

_RECORD_PROMPT = """

规则:
1. 不要模拟工具调用,不要生成<tool_call>或bash代码块
2. 只回复自然语言
3. 记录纪律:
   - Route E/F(团队/分配/成员)讨论 → 末尾必须输出 ---记录---
   - 其他路由 → 判断是否"值得记"再输出
   ---记录---
   log [分类] 事件描述
   member 人名 内容(触发条件标签)
4. log分类前缀(必带):
   [分配]人员安排/职责变动 | [人员]成员状态/评价 | [任务]任务完成/状态
   [风险]问题/风险 | [汇报]向上汇报 | [外部]外部通知 | [系统]自动事件
5. log一句一事,带分类前缀。member只写对人员画像有改变的信息。
   不匹配触发条件的不写member。没有记录不输出---记录---段。"""


def parse_records(reply):
    if "---记录---" not in reply:
        return None, reply
    parts = reply.split("---记录---", 1)
    clean = parts[0].strip()
    records = []
    for line in parts[1].strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        space = line.find(" ")
        if space < 0:
            continue
        rtype = line[:space].strip()
        rcontent = line[space:].strip()
        if rtype and rcontent:
            records.append((rtype, rcontent))
    return records, clean


def distribute_records(records):
    for rtype, rcontent in records:
        if rtype == "log":
            append_log(rcontent)
        elif rtype == "member":
            space = rcontent.find(" ")
            if space > 0:
                update_member_portrait(rcontent[:space].strip(),
                                       rcontent[space:].strip())


# ── Auto-record ──

def _matched_route_e(msg):
    return any(kw in msg for kw in ("团队", "领导", "分配", "汇报", "纪要"))

def _auto_record_e(user_msg, tool_output):
    summary = user_msg[:40]
    append_log(f"[系统] Route E: {summary}")
    if tool_output:
        topic = summary[:20]
        content = tool_output[:200]
        run_tool(["python3", os.path.join(PROJECT_ROOT,
                  "tools/observation_writer/write_observation.py"),
                  topic, content])

def _auto_record_f(name):
    append_log(f"[系统] Route F: 查询 {name}")

WORK_DATE_KEYWORDS = ("工作", "安排", "明天", "今天", "本周", "本月", "待办")

def _check_and_prefill(message):
    """检查本月是否已预填, 未填则自动补(仅工作查询时触发)"""
    if not any(kw in message for kw in WORK_DATE_KEYWORDS):
        return
    marker_path = os.path.join(PROJECT_ROOT, "memory", "tasks.md")
    if os.path.exists(marker_path):
        with open(marker_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("> 上月预填: "):
                    marker = line.strip()[len("> 上月预填: "):]
                    today = datetime.date.today()
                    expected = f"{today.year}-{today.month:02d}"
                    if marker == expected:
                        return
    run_tool(["python3", os.path.join(PROJECT_ROOT,
              "tools/task_manager/prefill_tasks.py")])

# ── Shortcut routing ──

def try_shortcut(message):
    t = message.strip().lower()
    if len(t) > 10:
        return None
    name, _ = detect_member(t)
    if name:
        return None
    for keywords, tool_rel in _SHORTCUTS:
        if any(kw in t for kw in keywords):
            return run_tool(["python3", os.path.join(PROJECT_ROOT, tool_rel)])
    return None


# ── Main flow ──

def process_message(message, session_id="default"):
    # A: Simple replies
    stripped = message.strip().lower()
    if stripped in _SIMPLE:
        r = _SIMPLE[stripped]
        h = load_history(session_id)
        h["messages"].append({"role": "user", "content": message})
        h["messages"].append({"role": "assistant", "content": r})
        trim_history(h); save_history(session_id, h)
        return r

    # H: Comfort
    if any(kw in message.lower() for kw in
           ["心累", "焦虑", "此心安处", "难受", "压力", "不开心"]):
        return _handle_comfort(message, session_id)

    # B/D/E: Shortcut without LLM
    shortcut = try_shortcut(message)
    if shortcut:
        h = load_history(session_id)
        h["messages"].append({"role": "user", "content": message})
        h["messages"].append({"role": "assistant", "content": shortcut})
        trim_history(h); save_history(session_id, h)
        if _matched_route_e(message):
            _auto_record_e(message, shortcut)
        return shortcut

    # Person detection (used for both shortcut and LLM context)
    member_name, member_path = detect_member(message)

    # F: Member name shortcut (≤10 chars, pure info query, no B/D/E keywords)
    if member_name and len(message.strip()) <= 10:
        t = message.strip().lower()
        is_be_de = any(kw in t for kw in ["安排", "待办", "排班", "完成", "清理",
                                           "制度", "流程", "手册", "台账", "规范",
                                           "团队", "领导", "分配", "汇报", "纪要"])
        if not is_be_de:
            output = run_tool(["python3", os.path.join(PROJECT_ROOT,
                              "tools/team_router/route_member.py"), member_name])
            h = load_history(session_id)
            h["messages"].append({"role": "user", "content": message})
            h["messages"].append({"role": "assistant", "content": output})
            trim_history(h); save_history(session_id, h)
            _auto_record_f(member_name)
            return output

    member_ctx = ""
    if member_name:
        member_ctx = f"\n\n[成员档案 {member_name}]\n" + get_member_context(member_path)

    # Check prefill for work-related queries (before LLM)
    _check_and_prefill(message)

    # Build context
    agents_md = read_file(os.path.join(PROJECT_ROOT, "AGENTS.md"))
    logs_summary = get_logs_summary()
    h = load_history(session_id)

    system = f"你是一个工班AI助手，运行在轻量 Python 路由器上。你没有工具执行能力，不要模拟<tool_call>或bash命令。只回复自然语言。\n\n系统路由规则:\n{agents_md}"
    if member_ctx:
        system += member_ctx
    if logs_summary:
        system += f"\n\n[近况]\n{logs_summary}"
    system += _RECORD_PROMPT

    msgs = [{"role": "system", "content": system}]
    if h.get("summary"):
        msgs.append({"role": "system", "content": f"[对话摘要] {h['summary']}"})
    msgs.extend(h.get("messages", []))

    total = sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)
    if total > MAX_CONTEXT_CHARS:
        sys_msgs = [m for m in msgs if m["role"] == "system"]
        rest = [m for m in msgs if m["role"] != "system"]
        while rest and total > MAX_CONTEXT_CHARS:
            removed = rest.pop(0)
            total -= len(json.dumps(removed, ensure_ascii=False))
        msgs = sys_msgs + rest

    msgs.append({"role": "user", "content": message})
    reply = call_llm(msgs)

    records, clean = parse_records(reply)
    if records:
        distribute_records(records)
        reply = clean

    h["messages"].append({"role": "user", "content": message})
    h["messages"].append({"role": "assistant", "content": reply})
    trim_history(h); save_history(session_id, h)
    return reply


def _handle_comfort(text, session_id):
    comfort_dir = os.path.join(PROJECT_ROOT, "Knowledge", "此心安处")
    materials = ""
    if os.path.isdir(comfort_dir):
        parts = []
        for f in sorted(os.listdir(comfort_dir)):
            if f.endswith(".md"):
                content = read_file(os.path.join(comfort_dir, f))[:800]
                parts.append(f"--- {f} ---\n{content}")
        materials = "\n\n".join(parts)
    reply = call_llm([
        {"role": "system",
         "content": "你是一个温暖共情的倾听者。先关心对方怎么了"
         "，用以下材料给予安慰。语气温柔，不说教不分析。"
         f"\n\n参考资料：{materials}" if materials else ""},
        {"role": "user", "content": text}
    ])
    h = load_history(session_id)
    h["messages"].append({"role": "user", "content": text})
    h["messages"].append({"role": "assistant", "content": reply})
    trim_history(h); save_history(session_id, h)
    return reply


# ── REPL ──

def repl():
    sid = "terminal"
    print("Agent CLI — 内存 ~50MB | /exit 退出 | /clear 清空会话")
    while True:
        try:
            msg = input(">>> ").strip()
            if not msg: continue
            if msg == "/exit": break
            if msg == "/clear":
                save_history(sid, {"summary": "", "messages": []})
                print("[已清空]"); continue
            print(process_message(msg, sid))
        except KeyboardInterrupt:
            print("\n[退出]"); break
        except Exception as e:
            print(f"[错误: {e}]")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("message", nargs="*")
    p.add_argument("--repl", action="store_true")
    p.add_argument("--session", default="default")
    a = p.parse_args()
    if a.repl or (not a.message and sys.stdin.isatty()):
        repl(); return
    msg = " ".join(a.message) if a.message else ""
    if not msg and not sys.stdin.isatty():
        msg = sys.stdin.read().strip()
    if not msg:
        print("请输入消息"); sys.exit(1)
    print(process_message(msg, a.session))


if __name__ == "__main__":
    main()
