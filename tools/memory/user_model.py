#!/usr/bin/env python3
"""
user_model.py - 用户建模引擎
基于交互历史推断用户关注域，为 slow_think 提供上下文增强。
单用户场景：追踪关注域演化，而非多角色适配。
"""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.memory_core import MemoryCore


class UserContextTracer:
    DOMAINS = {
        "safety": ["安全", "事故", "隐患", "防护", "处罚", "整改", "消防", "演练", "检查"],
        "flood": ["暴雨", "台风", "积水", "排水", "防汛", "应急物资"],
        "quality": ["验收", "养护", "规范", "检测", "技术标准", "质量", "强度", "操作"],
        "schedule": ["工期", "计划", "滞后", "协调", "分配", "排班", "值班"],
        "paperwork": ["台账", "报表", "签字", "文件", "归档", "记录", "日志"],
        "personnel": ["团队", "成员", "考核", "评价", "借调", "调整", "负责"],
    }

    def __init__(self, core: MemoryCore):
        self.core = core

    def get_context(self, current_query: str, top_n=3):
        current_domain = self._classify(current_query)

        domain_history = self.core.search(
            query=f"domain:{current_domain}",
            types=["episodic"],
            top_k=top_n,
        )

        return {
            "active_domain": current_domain,
            "relevant_history": [h["c"] for h in domain_history.get("hits", [])],
            "note": f"检测到当前问题属于【{current_domain}】域，已自动加载相关历史经验。",
        }

    def _classify(self, query):
        best_domain = "general"
        best_score = 0

        for domain, keywords in self.DOMAINS.items():
            score = sum(1 for kw in keywords if kw in query)
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain


# ══════════════════════════════════════════════════════════════
# CLI test
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    core = MemoryCore(root_path="/home/admin/opencode")
    tracer = UserContextTracer(core)

    tests = [
        "明天暴雨预警，库房防汛物资够不够",
        "台账涂改被发现了怎么补救",
        "这个月考核细则变了，谁负责更新",
        "消防演练什么时候安排",
        "王继衡的排班下周怎么调",
    ]

    for q in tests:
        ctx = tracer.get_context(q, top_n=2)
        print(f"\nQ: {q}")
        print(f"  Domain: {ctx['active_domain']} ({len(ctx['relevant_history'])} historical)")
