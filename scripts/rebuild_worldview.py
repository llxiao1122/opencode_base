#!/usr/bin/env python3
"""重建世界观丰富实例集（以 VPS 15 实体标准为基础，扩充人员/文档/系统/区域/组织）。

数据源（全部确定性规则，无 LLM）：
  - team_work.json：组织关系 → 人员实体（角色/上下级/审批流）
  - Knowledge/*.md：制度文档 → 文档主题实体
  - 已知系统/区域/组织/地点清单 → 在 Knowledge 中出现才建（避免无依据实体）

不覆盖已有实体（跳过），重建 FAISS 分节索引。
用法: python3 scripts/rebuild_worldview.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.memory import worldview as wv

KNOWLEDGE_DIR = ROOT / "Knowledge"
TEAM_WORK_FILE = ROOT / "data" / "state" / "team_work.json"
TEAM_WORK_BAK = Path("/var/folders/8z/6j3zpvq11t37rffxnmsj7y480000gn/T/opencode/local_data_backup/team_work.json")

PERSON_TYPE = "person"
TOPIC_TYPE = "topic"

# ── 确定性实体清单 ──────────────────────────────────────────────

_EXTRA_PEOPLE = {
    "郝晓平": {"role": "上级领导（审批链末端）", "leader": True},
    "商丽娜": {"role": "副总·分管物资管理中心+财务部", "leader": True},
    "李彦奎": {"role": "部长·物资管理中心", "leader": True},
    "张新宇": {"role": "副经理·物资管理中心", "leader": True},
    "王敬宇": {"role": "主任·直接上级·物资管理中心", "leader": True},
    "卢丽英": {"role": "副主任·安全·物资管理中心物资调配室", "leader": True},
    "程智": {"role": "物资管理岗"},
    "王红义": {"role": "物资管理岗·捐赠验收推进"},
    "靳攀": {"role": "物资管理岗"},
    "刘朋": {"role": "物资管理岗"},
    "荆幸斌": {"role": "科室废旧危废总负责人·资产管理员"},
    "王超": {"role": "科室危废负责人·危废系统/联单/催办"},
    "张梦圆": {"role": "科室内勤(借调休假中)·考勤公文简报"},
}

_SYSTEMS = ["CIMS系统", "EAM系统", "HAP系统", "OA系统", "PDA", "SCM系统", "WMS系统",
            "i物资", "国家固废系统", "钉钉", "工班网盘", "仓储管理系统"]

_ZONES = ["材料棚", "立体库区", "中小件区", "大件库区", "空调库房", "杂品库",
          "料场", "物资总库", "废旧库区"]

_ORGS = ["安全管理部", "技术管理部", "物资管理中心", "生产中心", "财务管理部",
         "供建中心", "物资调配室", "郑州地铁集团有限公司"]

_PLACES = ["关陈车辆段", "南环车辆段", "圃田车辆段", "红石坡", "河西停车场"]


def _clean_doc_name(fname: str) -> str:
    """文档文件名 → 实体名：去编号前缀与版本后缀。"""
    name = fname
    name = re.sub(r"\.md$", "", name)
    name = re.sub(r"^\d+-", "", name)
    name = re.sub(r"-[A-Z]\d+(\.\d+)?$", "", name)
    return name


def _load_team_work() -> dict:
    for p in (TEAM_WORK_FILE, TEAM_WORK_BAK):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _find_source_docs(name: str, max_hits: int = 3) -> list[Path]:
    """在 Knowledge 中找包含实体名的文档（出现行数排序）。"""
    hits = []
    for md in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if md.name == "INDEX.md":
            continue
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        count = sum(1 for ln in lines if name in ln)
        if count:
            hits.append((count, md))
    hits.sort(key=lambda x: -x[0])
    return [md for _, md in hits[:max_hits]]


def _context_lines(md: Path, name: str, max_lines: int = 8) -> str:
    lines = md.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for i, ln in enumerate(lines):
        if name in ln:
            start, end = max(0, i - 1), min(len(lines), i + 2)
            ctx = "\n".join(l.strip() for l in lines[start:end] if l.strip())
            if ctx not in seen:
                seen.add(ctx)
                out.append(ctx)
        if len(out) >= max_lines:
            break
    return "\n\n".join(out)


def _build_person(name: str, role: str, team_work: dict, leader: bool = False) -> str:
    rel = []
    if leader:
        chain = team_work.get("hierarchy", {}).get("chain", "")
        rel.append(f"- **上级链**: {chain}")
    flows = team_work.get("approval_flows", {})
    involved = [f"{k}：{v}" for k, v in flows.items() if name in v]
    if involved:
        rel.append(f"- **审批流**: {'；'.join(involved)}")

    return "\n".join([
        "## 基本信息",
        f"- **姓名**: {name}",
        f"- **角色**: {role}",
        "- **工班成员**: false",
        "- **静态源**: data/state/team_work.json",
        "",
        "## 组织关系",
        "\n".join(rel) if rel else "- （待补充）",
        "",
        "## 关联制度",
        "- （关联制度待日常记录积累）",
        "",
        "## 近期事件（上限 30 条）",
        "（无）",
    ])


def _build_topic(name: str, src_paths: list[Path], ctx_hits: str = "") -> str:
    src_lines = "\n".join(f"- **静态源**: {p.relative_to(ROOT)}" for p in src_paths)
    if not ctx_hits:
        ctx_hits = "（内容待日常记录积累）"
    return "\n".join([
        "## 基本信息",
        f"- **实体名称**: {name}",
        f"- **实体类型**: {TOPIC_TYPE}",
        src_lines,
        "",
        "## 知识要点",
        ctx_hits,
        "",
        "## 关联实体",
        "（待发现）",
    ])


def _build_doc_entity(md: Path) -> str:
    lines = [l for l in md.read_text(encoding="utf-8").splitlines() if l.strip()]
    headers = [l.strip("# ").strip() for l in lines if l.startswith(("# ", "## ", "### "))]
    headers = list(dict.fromkeys(headers))[:12]
    head = "\n".join(lines[:10])[:500]
    tail = "\n".join(lines[-10:])[:300]
    parts = []
    if headers:
        parts.append("### 章节结构\n- " + "\n- ".join(headers))
    parts.append("### 文档开头\n" + head)
    if len(lines) > 20:
        parts.append("### 文档结尾\n" + tail)
    return "\n\n".join(parts)


def main():
    if not KNOWLEDGE_DIR.exists():
        print("Knowledge 目录不存在")
        return 1

    wv._ensure_dirs()
    idx = wv._load_index()
    existing = set(idx.get("entities", {}).keys())
    team_work = _load_team_work()
    created = {"person": [], "topic": []}

    # 1. 人员实体（跳过已有 9 人）
    for name, info in sorted(_EXTRA_PEOPLE.items()):
        if name in existing:
            continue
        content = _build_person(name, info["role"], team_work, info.get("leader", False))
        (wv.ENTITIES_DIR / f"{name}.md").write_text(content + "\n", encoding="utf-8")
        idx["entities"][name] = {"type": PERSON_TYPE, "updated": wv.datetime.now().isoformat()}
        created["person"].append(name)

    # 2. 文档主题实体
    for md in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if md.name == "INDEX.md":
            continue
        name = _clean_doc_name(md.name)
        if not name or name in existing:
            continue
        content = _build_doc_entity(md)
        entity = _build_topic(name, [md], content)
        (wv.ENTITIES_DIR / f"{name}.md").write_text(entity + "\n", encoding="utf-8")
        idx["entities"][name] = {"type": TOPIC_TYPE, "updated": wv.datetime.now().isoformat()}
        created["topic"].append(name)

    # 3. 系统/区域/组织/地点（文档校验，有依据才建）
    for group in (_SYSTEMS, _ZONES, _ORGS, _PLACES):
        for name in group:
            if name in existing:
                continue
            srcs = _find_source_docs(name)
            if not srcs:
                continue
            ctx = _context_lines(srcs[0], name)
            entity = _build_topic(name, srcs, ctx)
            (wv.ENTITIES_DIR / f"{name}.md").write_text(entity + "\n", encoding="utf-8")
            idx["entities"][name] = {"type": TOPIC_TYPE, "updated": wv.datetime.now().isoformat()}
            created["topic"].append(name)

    if not any(created.values()):
        print("无新实体（可能已全部存在）")
        return 0

    wv._save_index(idx)
    wv._rebuild_faiss()
    print(f"新增实体: person {len(created['person'])} = {created['person']}")
    print(f"         topic {len(created['topic'])}（共 {len(created['topic'])} 个）")
    print(f"实体总数: {len(idx['entities'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
