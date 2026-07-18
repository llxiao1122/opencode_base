#!/usr/bin/env python3
"""
curiosity_engine.py - 自主好奇引擎（主动探索，面向未来）
依附于 memory_core，在特定认知事件发生时，生成自主探索任务。
事件源：conflicts 检测、知识缺口扫描、高频异常模式

与 memory_reflect.py 的区别:
- curiosity_engine: 主动扫描 → 生成探索任务列表（what to learn next）
- memory_reflect:  被动回看 → 压缩/提炼已有记忆（what we learned before）
二者互补：curiosity 输出任务，reflect 输出模式。配合使用但不互相依赖。
"""

import sys, re, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.memory_core import MemoryCore


class CuriosityEngine:
    def __init__(self, core: MemoryCore):
        self.core = core

    def scan_and_generate_tasks(self):
        tasks = []
        tasks.extend(self._scan_unresolved_conflicts())
        tasks.extend(self._detect_knowledge_gaps())
        tasks.extend(self._detect_anomaly_patterns())
        return tasks

    # ══════════════════════════════════════════════════════════════
    # 事件源 1：未解决冲突
    # ══════════════════════════════════════════════════════════════

    def _scan_unresolved_conflicts(self):
        unresolved = self.core.get_unresolved_conflicts()
        tasks = []
        for conf in unresolved:
            tasks.append({
                "type": "curiosity_conflict",
                "priority": "high",
                "trigger": f"记忆冲突: {conf.get('detail', '')}",
                "conflict_id": conf["id"],
                "episodes": conf.get("items", []),
                "occurrences": conf.get("occurrences", 1),
                "question": (
                    f"以下两条经验存在矛盾：\n"
                    f"涉及条目: {', '.join(conf.get('items', []))}\n"
                    f"详情: {conf.get('detail', '')}\n"
                    f"已出现 {conf.get('occurrences', 1)} 次，请调用 slow_think 深度对比分析差异原因。"
                ),
                "suggested_action": "调用 slow_think 进行深度对比，若无法消解则标记为需人工裁决",
                "created_at": datetime.now().isoformat(),
            })
        return tasks

    # ══════════════════════════════════════════════════════════════
    # 事件源 2：知识缺口
    # ══════════════════════════════════════════════════════════════

    def _detect_knowledge_gaps(self):
        knowledge_dir = self.core.root / "Knowledge"
        if not knowledge_dir.exists():
            return []

        gaps = []
        existing_files = {f.stem for f in knowledge_dir.glob("*.md")}

        pattern = re.compile(
            r'(?:GB|GB/T|JGJ|CJJ|DL|TB|JTJ)\s*[-/]?\s*\d+(?:\.\d+)*'
            r'|见《([^》]+)》'
            r'|参照《([^》]+)》'
            r'|详见《([^》]+)》'
        )

        for md_file in sorted(knowledge_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding='utf-8')
            except Exception:
                continue

            for match in pattern.finditer(content):
                groups = match.groups()
                ref_text = match.group(0)
                if groups[0] or groups[1] or groups[2]:
                    ref_text = next(g for g in groups if g)

                clean = ref_text.strip()
                if not clean or len(clean) < 2:
                    continue

                if clean in existing_files:
                    continue
                if any(clean in f for f in existing_files):
                    continue

                gaps.append({
                    "source_file": md_file.name,
                    "missing_reference": clean,
                    "context": self._extract_sentence(content, match.start()),
                })

        # Deduplicate by reference
        seen = set()
        unique = []
        for g in gaps:
            key = g["missing_reference"]
            if key not in seen:
                seen.add(key)
                unique.append(g)

        tasks = []
        for gap in unique:
            tasks.append({
                "type": "curiosity_gap",
                "priority": "medium",
                "trigger": f"知识缺口: 文件 {gap['source_file']} 引用了 {gap['missing_reference']} 但知识库中无此文",
                "question": (
                    f"文件 {gap['source_file']} 中引用了: {gap['missing_reference']}\n"
                    f"上下文: {gap['context']}\n"
                    f"建议补充该规范原文到 Knowledge 目录。"
                ),
                "suggested_action": f"查找并录入 {gap['missing_reference']} 相关内容",
                "created_at": datetime.now().isoformat(),
            })
        return tasks

    def _extract_sentence(self, content, pos):
        start = max(0, pos - 40)
        end = min(len(content), pos + 60)
        snippet = content[start:end].replace('\n', ' ')
        return f"…{snippet}…"

    # ══════════════════════════════════════════════════════════════
    # 事件源 3：高频异常模式
    # ══════════════════════════════════════════════════════════════

    def _detect_anomaly_patterns(self, window_days=14):
        results = self.core.search(
            query="异常 故障 隐患 事故 整改 重复",
            types=["episodic"],
            top_k=20,
        )
        hits = results.get("hits", [])
        if len(hits) < 3:
            return []

        chunks = [h["c"] for h in hits]
        if len(set(chunks)) < 3:
            return []

        unique = list(set(chunks))
        if len(unique) < 3:
            return []

        return [{
            "type": "curiosity_pattern",
            "priority": "low",
            "trigger": f"高频异常: 近{window_days}天内出现了 {len(unique)} 个不同的异常相关事件",
            "question": f"最近 {window_days} 天内记录了 {len(unique)} 个异常事件，建议检查是否有重复模式。",
            "suggested_action": "运行 memory_reflect 进行经验提炼",
            "created_at": datetime.now().isoformat(),
        }]


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    core = MemoryCore(root_path="/home/admin/opencode")
    ce = CuriosityEngine(core)
    tasks = ce.scan_and_generate_tasks()
    print(json.dumps(tasks, ensure_ascii=False, indent=2))
    print(f"\n共生成 {len(tasks)} 个自主探索任务")
