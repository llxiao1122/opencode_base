#!/usr/bin/env python3
"""
keyword_discovery.py — 离线关键词挖掘器。

模式一 (默认):
  python3 tools/keyword_discovery.py
  读 unknowns.log → 调 LLM 分析 → 输出 pending_keywords.json

模式二:
  python3 tools/keyword_discovery.py --apply
  读 pending_keywords.json → 自动注入 route_request.py

模式三:
  python3 tools/keyword_discovery.py --top 100
  自定义处理最近 N 条未命中输入
"""

import sys, json, re, os
from pathlib import Path
from collections import OrderedDict

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from llm_client import call as _llm_call


def _load_unknowns(limit=50):
    """读 unknowns.log, 去重, 返回最近 N 条输入原文。"""
    log_path = ROOT / "memory" / "unknowns.log"
    if not log_path.exists():
        return []
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    inputs = []
    seen = set()
    for line in reversed(lines):
        if "|" not in line:
            continue
        text = line.split("|", 1)[-1].strip()
        if text and text not in seen:
            seen.add(text)
            inputs.append(text)
        if len(inputs) >= limit:
            break
    return inputs


def _load_current_keywords():
    """从 route_request.py 提取当前所有路由的关键词集。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("route_request", str(TOOLS_DIR / "route_request.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {
        "A": [],
        "B": getattr(mod, "B_KEYWORDS", None) or ["安排", "待办", "排班", "完成", "清理"],
        "C": getattr(mod, "C_KEYWORDS", None) or ["改", "跑", "部署", "编辑", "修复", "优化", "重启", "安装", "卸载", "编译"],
        "D": getattr(mod, "D_KEYWORDS", []),
        "E": getattr(mod, "E_KEYWORDS", None) or ["团队", "工班", "领导", "分配", "汇报", "纪要", "调度", "协调", "上报"],
        "F": getattr(mod, "MEMBER_NAMES", []),
        "G": getattr(mod, "G_KEYWORDS", None) or ["事后经验", "复盘", "把这次", "记下来", "总结"],
        "H": getattr(mod, "H_KEYWORDS", None) or ["此心安处", "心累", "焦虑", "意义", "思考", "思想", "没有意义", "不想干", "心情", "压力"],
        "I": getattr(mod, "I_KEYWORDS", None) or ["分析", "评估", "方案", "根因", "为什么", "排查", "对比", "研判", "利弊", "推演"],
    }


def _build_prompt(unknowns, keywords):
    """构建 LLM 分析 prompt。"""
    ctx_path = TOOLS_DIR / "domain_context.md"
    agents_path = ROOT / "AGENTS.md"
    ctx_text = ctx_path.read_text(encoding="utf-8") if ctx_path.exists() else ""
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

    kw_lines = "\n".join(f"  {r}: {', '.join(kws)}" for r, kws in sorted(keywords.items()))
    unknowns_text = "\n".join(f"- {u}" for u in unknowns)

    return f"""你是工班AI的离线关键词挖掘器。以下输入未被硬编码路由命中。

## 领域上下文
{ctx_text}

## 路由定义
{agents_text}

## 当前关键词
{kw_lines}

## 未命中输入
{unknowns_text}

## 任务
分析每条未命中输入应归入哪个路由（A~I）。给出建议的新关键词。
注意: 如果输入是闲聊/非工作内容, route=A, keywords=[]。

输出 JSON 数组, 不要额外文字:
[
  {{"input": "...", "route": "E", "keywords": ["周报", "提交"]}},
  {{"input": "...", "route": "A", "keywords": []}}
]"""


def discover(top=50):
    """主流程: 读 log → LLM 分析 → 写 pending_keywords.json"""
    unknowns = _load_unknowns(top)
    if not unknowns:
        print("No unknown inputs found. unknowns.log is empty or missing.")
        return None

    keywords = _load_current_keywords()
    prompt = _build_prompt(unknowns, keywords)

    print(f"Analyzing {len(unknowns)} unknown inputs via LLM...")
    raw = _llm_call(prompt, max_tokens=2000, temperature=0.2, timeout=60)

    if isinstance(raw, dict) and "error" in raw:
        print(f"LLM error: {raw['error']}")
        return None

    # Extract JSON
    text = str(raw)
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        print("Failed to parse LLM response. Raw output saved to memory/pending_keywords.raw.txt")
        (ROOT / "memory" / "pending_keywords.raw.txt").write_text(text, encoding="utf-8")
        return None

    try:
        suggestions = json.loads(m.group(0))
    except json.JSONDecodeError:
        print("JSON parse error. Raw output saved to memory/pending_keywords.raw.txt")
        (ROOT / "memory" / "pending_keywords.raw.txt").write_text(text, encoding="utf-8")
        return None

    # Deduplicate within suggestions
    seen = set()
    unique = []
    for s in suggestions:
        key = (s.get("route", ""), tuple(sorted(s.get("keywords", []))))
        if key not in seen:
            seen.add(key)
            unique.append(s)

    out_path = ROOT / "memory" / "pending_keywords.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    print(f"Written {len(unique)} suggestions to {out_path}")
    for s in unique:
        kws = s.get("keywords", [])
        print(f"  Route {s['route']}: {s['input'][:40]}  →  {', '.join(kws) if kws else '(闲聊,无关键词)'}")

    return unique


def apply():
    """读 pending_keywords.json, 注入 route_request.py。"""
    pend_path = ROOT / "memory" / "pending_keywords.json"
    if not pend_path.exists():
        print("pending_keywords.json not found. Run discover first.")
        return

    suggestions = json.loads(pend_path.open("r", encoding="utf-8"))
    rt_path = TOOLS_DIR / "route_request.py"

    if not rt_path.exists():
        print("route_request.py not found")
        return

    content = rt_path.read_text(encoding="utf-8")

    # 收集每个路由的新关键词
    current = _load_current_keywords()
    added = OrderedDict()
    for s in suggestions:
        route = s.get("route", "A")
        if route == "A":
            continue
        kws = s.get("keywords", [])
        existing = current.get(route, [])
        new = [kw for kw in kws if kw not in existing]
        if new:
            added.setdefault(route, []).extend(new)

    if not added:
        print("No new keywords to add. All keywords already exist.")
        return

    print("Adding keywords:")
    for route, kws in added.items():
        deduped = list(OrderedDict.fromkeys(kws))
        added[route] = deduped
        print(f"  Route {route}: {', '.join(deduped)}")

    # 注入: 找到各路由的关键词列表, 追加新词
    # D 路由用 D_KEYWORDS 变量, 其他路由用内联列表
    for route, kws in added.items():
        new_kw = ", ".join(f'"{kw}"' for kw in kws)

        if route == "D":
            # D_KEYWORDS 是一个列表变量, 找到最后一个元素后面插入
            pattern = r'(\[\s*\n)((?:\s*".*?"[,\n\s]*)+)(\s*\])'
            match = re.search(pattern, content, re.DOTALL)
            if not match:
                # Try inlined format
                pattern = r'(\[\s*".*?")(\s*\])'
                match = re.search(pattern, content)
            if match:
                insert_pos = match.end(2) if match.lastindex >= 2 else match.end(1)
                insertion = f",\n    {new_kw}"
                content = content[:insert_pos] + insertion + content[insert_pos:]
        else:
            # 内联关键词列表: ["keyword1", "keyword2", ...] or [\n"k1",\n"k2"\n]
            # 找到对应路由行, 在最后一个关键词后插入
            route_label = {
                "B": "安排", "C": "改", "E": "团队", "F": "成员",
                "G": "事后经验", "H": "此心安处", "I": "分析",
            }
            anchor = route_label.get(route, "")
            if anchor:
                # 找到包含 anchor 的行, 在行末关键词列表末尾插入
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if f"\"{anchor}\"" in line and "_has_any" in line:
                        # 找到该行的最后一个引号后
                        last_quote = line.rfind('"])')
                        if last_quote >= 0:
                            lines[i] = line[:last_quote + 1] + f", {new_kw}" + line[last_quote + 1:]
                        break
                content = "\n".join(lines)

    rt_path.write_text(content, encoding="utf-8")
    print(f"\nWritten to {rt_path}")

    # 清空 unknowns.log
    log_path = ROOT / "memory" / "unknowns.log"
    log_path.write_text("", encoding="utf-8")
    print(f"Cleared {log_path}")


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply()
    else:
        # 解析 --top N
        top = 50
        for i, arg in enumerate(sys.argv):
            if arg == "--top" and i + 1 < len(sys.argv):
                try:
                    top = int(sys.argv[i + 1])
                except ValueError:
                    pass
        discover(top=top)
