"""
knowledge/retriever.py — Knowledge retrieval interface.

Searches FAISS index and returns matching knowledge chunks.
Independent of memory_search (episodic) — does not query task/event data.
"""

from knowledge.indexer import search as _faiss_search
from knowledge.store import load_all, find_by_id


def search(query: str, top_k: int = 5, include_archived: bool = False) -> list:
    """Search knowledge base and return matching chunks with metadata.

    Lifecycle rules (auto-applied):
        - archived chunks excluded from default search
        - deprecated chunks downweighted ×0.3, marked "(已废止)"
        - active chunks returned at full score

    Args:
        query: natural language query
        top_k: max results to return
        include_archived: if True, include archived chunks (default: False)

    Returns:
        [{id, source_file, section_path, text, score, type, status, version}, ...]
    """
    hits = _faiss_search(query, top_k=top_k * 2)  # oversample to account for filtering
    if not hits:
        return []

    all_entries = {e["id"]: e for e in load_all()}
    results = []
    for score, chunk_idx in hits:
        entry = all_entries.get(f"kb_{_idx_to_id(chunk_idx)}", None)
        if not entry:
            entry = _find_by_position(chunk_idx)

        if not entry:
            continue

        status = entry.get("status", "active")

        # Exclude archived by default
        if status == "archived" and not include_archived:
            continue

        adjusted_score = score
        deprecation_note = ""

        if status == "deprecated":
            adjusted_score = round(score * 0.3, 3)
            deprecation_note = "(已废止)"
        elif status == "archived":
            deprecation_note = "(已归档)"

        results.append({
            "id": entry.get("id", ""),
            "source_file": entry.get("source_file", ""),
            "base_name": entry.get("base_name", ""),
            "version": entry.get("version", "v1"),
            "section_path": entry.get("section_path", []),
            "text": entry.get("text", ""),
            "score": adjusted_score,
            "raw_score": score,
            "type": entry.get("type", "reference"),
            "status": status,
            "note": deprecation_note,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def retrieve(topic: str, max_chars: int = 2000) -> str:
    """Search and return concatenated knowledge text for LLM context.

    Args:
        topic: search query
        max_chars: max total characters returned

    Returns:
        formatted knowledge text blocks with deprecation markers
    """
    results = search(topic, top_k=3)
    if not results:
        return ""

    parts = []
    total = 0
    for r in results:
        section = " > ".join(r["section_path"]) if r["section_path"] else r["source_file"]
        header = f"【{section}】{r['note']}" if r.get("note") else f"【{section}】"
        block = f"{header}\n{r['text']}"
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 50:
                parts.append(block[:remaining])
            break
        parts.append(block)
        total += len(block) + 1

    return "\n\n".join(parts)


def _idx_to_id(idx: int) -> str:
    """Convert a FAISS index position to ID suffix."""
    return f"{idx:04d}"


def _find_by_position(idx: int) -> dict:
    """Fallback: find entry by position in loaded list."""
    entries = load_all()
    if 0 <= idx < len(entries):
        return entries[idx]
    return {}
