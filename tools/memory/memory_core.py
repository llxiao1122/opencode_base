#!/usr/bin/env python3
"""
memory_core.py — 工班 AI 记忆核心引擎
Pure logic layer. No MCP protocol, no network dependencies.
"""

import json, os, sys, re, hashlib, threading, time
from pathlib import Path
from datetime import datetime, date, timedelta
from functools import lru_cache

import faiss
import numpy as np


# ═══════════════════════════════════════════════════════════════════════
# Global utilities
# ═══════════════════════════════════════════════════════════════════════

def _atomic_write(filepath, data):
    tmp = Path(str(filepath) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)


# ═══════════════════════════════════════════════════════════════════════
# MemoryCore
# ═══════════════════════════════════════════════════════════════════════

class MemoryCore:
    def __init__(self, root_path=""):
        if not root_path:
            root_path = str(Path(__file__).resolve().parent.parent.parent)
        self.root = Path(root_path)
        self.vec_dir = self.root / "memory" / ".vector"
        self.vec_dir.mkdir(parents=True, exist_ok=True)

        self.knowledge_dir = self.root / "Knowledge"
        self.obs_dir = self.root / "memory" / "observations"
        self.log_dir = self.root / "memory"

        # Metadata
        self.meta = self._load_meta()
        self.dim = 384

        # Embedding model (lazy load)
        self._model = None

        # FAISS indices
        self.sem_index = self._load_index("semantic")
        self.epi_index = self._load_index("episodic")

        # State
        self._pending_scores = []
        self._last_compress = self.meta.get("_last_compress", 0)

        # LLM config
        self._llm_api_url = os.environ.get("LLM_API_URL", "")
        self._llm_api_key = os.environ.get("LLM_API_KEY", "")
        self._llm_model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

        # Auto-build if indices are missing (not empty—empty means never built)
        if self.sem_index is None:
            self.sem_index = self._create_index()
        if self.epi_index is None:
            self.epi_index = self._create_index()

        self._warmup_cache()

    # ---- model ----
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
        return self._model

    # ---- metadata ----
    def _load_meta(self):
        path = self.vec_dir / "chunk_map.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        default = {"id_map": {}, "deleted_ids": [], "new_since_rebuild": 0, "_last_compress": 0, "conflicts_registry": []}
        _atomic_write(path, default)
        return default

    def _save_meta(self):
        _atomic_write(self.vec_dir / "chunk_map.json", self.meta)

    # ---- FAISS index ----
    def _load_index(self, name):
        path = self.vec_dir / f"{name}.index"
        if path.exists():
            return faiss.read_index(str(path))
        return None

    def _save_index(self, name, index):
        path = self.vec_dir / f"{name}.index"
        faiss.write_index(index, str(path))

    def _create_index(self):
        return faiss.IndexFlatIP(self.dim)

    # ---- embedding helpers ----
    def _embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        vecs = self.model.encode(texts, normalize_embeddings=True)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        return vecs.astype(np.float32)

    # ---- chunking ----
    def _chunk_markdown(self, filepath, max_chars=500, max_chunks=20):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()[:100000]  # cap at 100KB per file
        except Exception:
            return []
        paras = re.split(r'\n\n+', text)
        chunks = []
        current = ""
        for p in paras:
            p = p.strip()
            if not p:
                continue
            if len(current) + len(p) + 2 <= max_chars:
                current += ("\n\n" + p) if current else p
            else:
                if current:
                    chunks.append(current[:max_chars])
                    if len(chunks) >= max_chunks:
                        return chunks
                current = p
        if current and len(chunks) < max_chunks:
            chunks.append(current[:max_chars])
        return chunks

    # ---- extract topic ----
    def _extract_topic(self, situation):
        t = situation.replace("情境:", "").replace(" ", "").strip()
        return (t[:30] + "…") if len(t) > 30 else t or "未分类"

    # ══════════════════════════════════════════════════════════════
    # search
    # ══════════════════════════════════════════════════════════════

    @lru_cache(maxsize=256)
    def _search_raw(self, query: str, types_tuple: tuple) -> str:
        hits = []
        type_set = set(types_tuple)
        qvec = self._embed(query)

        def _collect(name, index, prefix, date_key, source_key):
            if index is None or index.ntotal == 0:
                return
            D, I = index.search(qvec, min(10, index.ntotal))
            for dist, idx in zip(D[0], I[0]):
                if idx < 0:
                    continue
                eid = f"{prefix}-{idx:04d}"
                entry = self.meta["id_map"].get(eid)
                if not entry:
                    continue
                r = float(dist)
                if entry.get("weight", 1.0) < 1.0:
                    r *= entry["weight"]
                hit = {
                    "t": prefix,
                    "id": eid,
                    "c": entry.get("chunk", ""),
                    "r": round(r, 3),
                }
                if date_key:
                    hit["d"] = entry.get(date_key, "")
                if source_key:
                    hit["s"] = entry.get(source_key, "")
                # future agent fields
                hit["rl"] = None
                hit["cr"] = None
                hits.append(hit)

        if "episodic" in type_set:
            _collect("episodic", self.epi_index, "ep", "date", None)
        if "semantic" in type_set:
            _collect("semantic", self.sem_index, "sem", None, "source")

        hits.sort(key=lambda h: h["r"], reverse=True)
        return json.dumps(hits, ensure_ascii=False)

    def search(self, query, types=None, top_k=5):
        types = tuple(sorted(types or ["episodic", "semantic"]))
        raw = self._search_raw(query, types)
        hits = json.loads(raw)
        return {"hits": hits[:top_k]}

    # ══════════════════════════════════════════════════════════════
    # retrieve
    # ══════════════════════════════════════════════════════════════

    def retrieve(self, topic, max_chars=2000):
        hits = self.search(topic, types=["semantic"], top_k=3)
        result = ""
        for h in hits["hits"]:
            chunk = h["c"]
            if len(result) + len(chunk) > max_chars:
                chunk = chunk[:max_chars - len(result)]
            source = h.get("s", "")
            result += f"\n【{source}】\n{chunk}\n"
            if len(result) >= max_chars:
                break
        return {"result": result.strip() or "未找到相关内容"}

    # ══════════════════════════════════════════════════════════════
    # save
    # ══════════════════════════════════════════════════════════════

    def save(self, situation, action, outcome, importance="medium"):
        importance = self._assess_importance(situation, action, outcome, importance)
        topic = self._extract_topic(situation)

        today = date.today().isoformat()
        text = f"情境:{situation} 行动:{action} 结果:{outcome}"

        # Write to ObservationStore (auto-routes by entity name)
        try:
            from memory.observation_store import write as obs_write
            obs_write(text, source="mcp_save", obs_type="note", layer="rule",
                      confidence={"high": 0.9, "medium": 0.7, "low": 0.5}.get(importance, 0.7))
        except Exception:
            pass
        vec = self._embed(text)

        index = self.epi_index or self._create_index()
        new_id = index.ntotal
        index.add(vec)
        self.epi_index = index
        self._save_index("episodic", index)

        entry_id = f"ep-{new_id:04d}"
        self.meta["id_map"][entry_id] = {
            "date": today,
            "chunk": text,
            "importance": importance,
            "topic": topic,
        }
        self.meta["new_since_rebuild"] = self.meta.get("new_since_rebuild", 0) + 1
        self._save_meta()

        self._search_raw.cache_clear()
        self._async_llm_score(entry_id, text)
        self._maybe_rebuild()

        return {"status": "ok", "id": entry_id, "importance": importance}

    # ══════════════════════════════════════════════════════════════
    # conflict registry (for curiosity engine)
    # ══════════════════════════════════════════════════════════════

    def register_conflict(self, conflict):
        """持久化一条冲突，去重：相同 items+nature 则只更新 last_seen"""
        registry = self.meta.setdefault("conflicts_registry", [])
        items = sorted(conflict.get("items") or [])
        nature = conflict.get("nature", "")
        now = datetime.now().isoformat()

        for existing in registry:
            if sorted(existing.get("items") or []) == items and existing.get("nature") == nature:
                existing["last_seen"] = now
                existing["occurrences"] = existing.get("occurrences", 1) + 1
                self._save_meta()
                return {"status": "updated", "id": existing["id"]}

        cid = f"conf-{len(registry)+1:03d}"
        entry = {
            "id": cid,
            "items": items,
            "nature": nature,
            "detail": conflict.get("detail", ""),
            "first_detected": now,
            "last_seen": now,
            "occurrences": 1,
            "status": "unresolved",
            "resolution_note": "",
        }
        registry.append(entry)
        self._save_meta()
        return {"status": "new", "id": cid}

    def get_unresolved_conflicts(self):
        """返回所有未解决的冲突（供 curiosity_engine 使用）"""
        return [c for c in self.meta.get("conflicts_registry", [])
                if c.get("status") == "unresolved"]

    # ══════════════════════════════════════════════════════════════
    # reflect
    # ══════════════════════════════════════════════════════════════

    def reflect(self, since_days=7):
        since_date = date.today() - timedelta(days=since_days)
        scanned = 0
        for f in sorted(self.obs_dir.glob("*.md")):
            fname = f.name.replace(".md", "")
            try:
                if date.fromisoformat(fname) >= since_date:
                    scanned += 1
            except ValueError:
                pass

        clusters = self._cluster_by_topic(since_days=since_days)
        compressed = self._compress_if_needed(clusters)

        return {
            "period": f"近{since_days}天",
            "files_scanned": scanned,
            "compressed": compressed,
        }

    # ══════════════════════════════════════════════════════════════
    # importance assessment
    # ══════════════════════════════════════════════════════════════

    def _assess_importance(self, situation, action, outcome, manual="medium"):
        HIGH = ["事故", "安全", "违规", "停电", "火灾", "塌方", "暴雨", "台风",
                "上级检查", "审计", "问责", "处罚", "隐患", "应急", "危险",
                "消防", "过期", "演练", "整改"]
        LOW = ["日常", "打印", "领取", "签到", "打扫", "普通", "常规", "正常"]

        text = f"{situation}{action}{outcome}"
        rule_score = "medium"
        if any(k in text for k in HIGH):
            rule_score = "high"
        elif any(k in text for k in LOW):
            rule_score = "low"

        rank = {"high": 3, "medium": 2, "low": 1}
        return max(rule_score, manual, key=lambda x: rank.get(x, 2))

    def _async_llm_score(self, entry_id, text):
        if not self._llm_api_url:
            return

        def _run():
            try:
                import urllib.request
                body = json.dumps({
                    "model": self._llm_model,
                    "messages": [{"role": "user",
                                   "content": f"仅返回高/中/低：{text[:200]}"}],
                    "max_tokens": 3,
                }).encode()
                headers = {"Content-Type": "application/json"}
                if self._llm_api_key:
                    headers["Authorization"] = f"Bearer {self._llm_api_key}"
                req = urllib.request.Request(self._llm_api_url, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                    raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    raw = raw.strip().replace("高", "high").replace("中", "medium").replace("低", "low")
                    if raw in ("high", "medium", "low"):
                        self._pending_scores.append((entry_id, raw))
                        self._flush_scores()
            except Exception:
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _flush_scores(self):
        if not self._pending_scores:
            return
        changed = False
        for eid, llm_score in self._pending_scores:
            entry = self.meta["id_map"].get(eid)
            if entry:
                current = entry.get("importance", "medium")
                rank = {"high": 3, "medium": 2, "low": 1}
                if rank.get(llm_score, 2) > rank.get(current, 2):
                    entry["importance"] = llm_score
                    changed = True
        if changed:
            self._save_meta()
        self._pending_scores.clear()

    # ══════════════════════════════════════════════════════════════
    # rebuild
    # ══════════════════════════════════════════════════════════════

    def _maybe_rebuild(self):
        deleted = len(self.meta.get("deleted_ids", []))
        new = self.meta.get("new_since_rebuild", 0)
        if deleted >= 200 or new >= 500:
            self._rebuild_full()

    def _rebuild_full(self):
        id_map = {}
        for idx_type, src_dir in [("semantic", self.knowledge_dir), ("episodic", self.obs_dir)]:
            new_index = self._create_index()
            counter = 0
            prefix = "sem" if idx_type == "semantic" else "ep"

            if src_dir.exists():
                for fpath in sorted(src_dir.rglob("*.md")):
                    if fpath.name.startswith("_"):
                        continue
                    chunks = self._chunk_markdown(fpath)
                    if not chunks:
                        continue
                    for chunk in chunks:
                        vec = self._embed(chunk)
                        new_index.add(vec)
                        eid = f"{prefix}-{counter:04d}"
                        entry = {"chunk": chunk}
                        if idx_type == "semantic":
                            entry["source"] = str(fpath.relative_to(self.knowledge_dir))
                        else:
                            entry["date"] = str(date.today())
                        id_map[eid] = entry
                        counter += 1

            # Write rebuild
            tmp_path = self.vec_dir / f"{idx_type}.index.rebuild"
            faiss.write_index(new_index, str(tmp_path))
            # Atomic replace
            os.replace(str(tmp_path), str(self.vec_dir / f"{idx_type}.index"))

            if idx_type == "semantic":
                self.sem_index = faiss.read_index(str(self.vec_dir / "semantic.index"))
            else:
                self.epi_index = faiss.read_index(str(self.vec_dir / "episodic.index"))

        self.meta["id_map"] = id_map
        self.meta["deleted_ids"] = []
        self.meta["new_since_rebuild"] = 0
        self._save_meta()
        self._search_raw.cache_clear()
        self._warmup_cache()

    def _warmup_cache(self):
        """Pre-search hot queries to populate LRU cache after rebuild."""
        hot_path = self.root / "memory" / "hot_queries.txt"
        defaults = ["安全", "暴雨", "防汛", "台账", "检查", "消防"]

        queries = defaults
        if hot_path.exists():
            try:
                with open(hot_path, "r", encoding="utf-8") as f:
                    custom = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                if custom:
                    queries = custom[:20]
            except Exception:
                pass

        for q in queries:
            for tt in [("episodic",), ("semantic",), ("episodic", "semantic")]:
                try:
                    self._search_raw(q, tt)
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════════════
    # clustering
    # ══════════════════════════════════════════════════════════════

    def _cluster_by_topic(self, since_days=90):
        since_date = date.today() - timedelta(days=since_days)
        entries = []
        vectors = []

        if not self.obs_dir.exists():
            return {}

        # Scan old format (top-level date files) + new format (people/teams/leaders/*.md)
        scan_paths = list(self.obs_dir.glob("*.md"))  # old: 2026-07-19.md
        for sub in ["people", "teams", "leaders", "system"]:
            subdir = self.obs_dir / sub
            if subdir.exists():
                scan_paths.extend(subdir.glob("*.md"))

        for fpath in scan_paths:
            if fpath.name.startswith("_"):  # skip index files
                continue

            # Date-filter old format
            try:
                file_date = date.fromisoformat(fpath.name.replace(".md", ""))
                if file_date < since_date:
                    continue
            except ValueError:
                pass  # new format (person names), always include

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()

                # Parse old format: lines starting with "- "
                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("- ") and len(line) > 5:
                        entries.append({"text": line, "file": fpath.name})
                        v = self._embed(line)
                        vectors.append(v[0])

                # Parse new format: sections between "---"
                sections = text.split("\n---\n")
                for sec in sections:
                    sec = sec.strip()
                    if not sec or not sec.startswith("##"):
                        continue
                    # Extract the fact line (first non-empty line after metadata)
                    lines = sec.split("\n")
                    fact_line = ""
                    for l in lines[1:]:
                        l = l.strip()
                        if l and not l.startswith("source:") and not l.startswith("type:") and not l.startswith("layer:") and not l.startswith("evidence:") and not l.startswith("confidence:"):
                            fact_line = l
                            break
                    if fact_line and len(fact_line) > 5:
                        entries.append({"text": fact_line, "file": fpath.name})
                        v = self._embed(fact_line)
                        vectors.append(v[0])
            except Exception:
                continue

        if len(entries) < 3:
            return {}

        vecs = np.array(vectors, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = np.expand_dims(vecs, axis=0)
        if len(vecs) < 2:
            return {}
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        sim = np.dot(vecs, vecs.T) / np.dot(norms, norms.T)

        visited = set()
        clusters = {}
        for i in range(len(entries)):
            if i in visited:
                continue
            group = [i]
            for j in range(i + 1, len(entries)):
                if j in visited:
                    continue
                if sim[i][j] > 0.85:
                    group.append(j)
                    visited.add(j)
            if len(group) >= 3:
                key = f"cluster_{len(clusters):02d}"
                clusters[key] = [entries[g] for g in group]

        return clusters

    # ══════════════════════════════════════════════════════════════
    # compression
    # ══════════════════════════════════════════════════════════════

    def _compress_if_needed(self, clusters):
        now = time.time()
        if now - self._last_compress < 86400:
            return []

        if not clusters:
            return []

        compressed = []
        for key, group in clusters.items():
            group_text = "\n".join([e["text"] for e in group])
            rule = self._summarize(group_text)
            if not rule:
                continue

            rule_file = self.knowledge_dir / "经验提炼.md"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(rule_file, "a", encoding="utf-8") as f:
                f.write(f"- [{ts}] {rule}\n")

            compressed.append({"group": key, "rule": rule, "n": len(group)})

        if compressed:
            self._last_compress = now
            self.meta["_last_compress"] = now
            self._save_meta()
            self._rebuild_full()

        return compressed

    def _summarize(self, group_text):
        if self._llm_api_url:
            try:
                import urllib.request
                prompt = f"将以下多条经验总结为一条通用规则(30字以内)：\n{group_text[:500]}"
                body = json.dumps({
                    "model": self._llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 50,
                }).encode()
                headers = {"Content-Type": "application/json"}
                if self._llm_api_key:
                    headers["Authorization"] = f"Bearer {self._llm_api_key}"
                req = urllib.request.Request(self._llm_api_url, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            except Exception:
                pass
        # Fallback
        lines = group_text.split("\n")
        return f"经验提炼: {lines[0][:80]}" if lines else "未知经验"


# ══════════════════════════════════════════════════════════════
# CLI rebuild entry
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true", help="全量重建索引")
    p.add_argument("--search", type=str, help="测试搜索")
    p.add_argument("--save", nargs=3, metavar=("SITUATION","ACTION","OUTCOME"), help="测试保存经验")
    args = p.parse_args()

    core = MemoryCore(root_path=os.environ.get("MEMORY_DIR", ""))

    if args.rebuild:
        core._rebuild_full()
        print(json.dumps({"status": "ok", "sem": core.sem_index.ntotal, "epi": core.epi_index.ntotal}, ensure_ascii=False))

    if args.search:
        r = core.search(args.search, top_k=3)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    if args.save:
        r = core.save(args.save[0], args.save[1], args.save[2])
        print(json.dumps(r, ensure_ascii=False, indent=2))
