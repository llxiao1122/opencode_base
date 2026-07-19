#!/usr/bin/env python3
"""
knowledge_router - 知识库查询（只搜 .md 文本文件，不搜二进制）
搜索所有 README.md + 其他 .md 文件，返回文件路径+摘要
"""
import sys, json, re
from pathlib import Path

KB_DIR = Path("/home/admin/opencode/Knowledge")


def grep_md_files(keyword: str, search_dir: Path, max_files=5) -> list:
    hits = []
    for fpath in sorted(search_dir.rglob("*.md")):
        if not fpath.is_file() or len(hits) >= max_files:
            continue
        rel = str(fpath.relative_to(KB_DIR))
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read()
            # find first match and grab surrounding section (between ## headings or \n\n)
            idx = text.lower().find(keyword.lower())
            if idx < 0:
                continue
            # expand backward to section start
            start = text.rfind("\n## ", 0, idx)
            if start < 0:
                start = text.rfind("\n\n", 0, idx)
            if start < 0:
                start = max(0, idx - 200)
            # expand forward to section end
            end = text.find("\n## ", idx)
            if end < 0:
                end = text.find("\n\n", idx)
            if end < 0:
                end = min(len(text), idx + 500)
            ctx = text[start:end].strip()[:800]
            hits.append({"file": rel, "context": ctx})
        except (UnicodeDecodeError, OSError):
            continue
    return hits


def _sub_keywords(kw: str):
    """从长关键词生成子关键词用于回退"""
    yield kw
    parts = re.split(r"[的与和及\-]", kw)
    if len(parts) > 1:
        for p in parts:
            if len(p) >= 2:
                yield p
    # try first 2-char prefix
    for i in range(len(kw), 1, -1):
        sub = kw[:i]
        if 2 <= len(sub) < len(kw):
            yield sub


def query_knowledge(query: str) -> dict:
    kw = re.sub(r"[?？吗呢什么怎么如何哪里哪个啥]", "", query).strip()
    keywords = [k for k in re.split(r"[\s,，、/]+", kw) if len(k) > 1]
    if not keywords:
        keywords = [kw]

    all_hits = []
    seen_files = set()

    for base_kw in keywords[:2]:
        for sub_kw in _sub_keywords(base_kw):
            if len(seen_files) >= 5:
                break
            md_hits = grep_md_files(sub_kw, KB_DIR, max_files=5 - len(seen_files))
            for h in md_hits:
                if h["file"] not in seen_files:
                    seen_files.add(h["file"])
                    all_hits.append(h)

    results = all_hits[:5]

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
