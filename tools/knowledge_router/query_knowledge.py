#!/usr/bin/env python3
"""
knowledge_router - 知识库查询（只搜 .md 文本文件，不搜二进制）
搜索所有 README.md + 其他 .md 文件，返回文件路径+摘要
"""
import sys, json, re
from pathlib import Path

KB_DIR = Path("/home/admin/opencode/Knowledge")


def grep_md_files(keyword: str, search_dir: Path, max_results=5) -> list:
    hits = []
    for fpath in sorted(search_dir.rglob("*.md")):
        if not fpath.is_file():
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if keyword.lower() in line.lower():
                        ctx = line.strip()[:120]
                        rel = str(fpath.relative_to(KB_DIR))
                        hits.append({"file": rel, "context": ctx})
                        if len(hits) >= max_results:
                            return hits
        except (UnicodeDecodeError, OSError):
            continue
    return hits


def query_knowledge(query: str) -> dict:
    kw = re.sub(r"[?？吗呢什么怎么如何哪里哪个啥]", "", query).strip()
    keywords = [k for k in re.split(r"[\s,，、/]+", kw) if len(k) > 1]
    if not keywords:
        keywords = [kw]

    all_hits = []
    seen = set()

    for kw in keywords[:2]:
        md_hits = grep_md_files(kw, KB_DIR)
        for h in md_hits:
            key = (h["file"], h.get("context", ""))
            if key not in seen:
                seen.add(key)
                all_hits.append(h)

    results = all_hits[:3]

    if not results:
        return {
            "status": "success",
            "query": " ".join(keywords),
            "matched_files": [],
            "content": {},
            "total_matches": 0,
            "note": "未在知识库中找到匹配，可尝试换关键词或问具体制度/流程"
        }

    content = {}
    for r in results:
        ctx = r.get("context", "")
        if ctx:
            content.setdefault(r["file"], []).append(ctx)

    return {
        "status": "success",
        "query": " ".join(keywords),
        "matched_files": list(dict.fromkeys(r["file"] for r in results)),
        "content": content,
        "total_matches": len(results)
    }


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    query = " ".join(args) if args else ""

    if not query and not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data:
                parsed = json.loads(data)
                query = parsed.get("query", "")
        except:
            pass

    if not query:
        print(json.dumps({"status": "error", "message": "请提供查询关键词"}, ensure_ascii=False))
        sys.exit(1)

    result = query_knowledge(query)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
