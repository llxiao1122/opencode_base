"""test_ssot_and_triggers.py — SSOT 一致性 + CognitiveLoop 触发 + MCP 握手"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

# ── 1. SSOT: Organization team members ──


def test_org_ssot_correct_members():
    """entity_index.json 是 SSOT，OrganizationModel 读出的成员必须匹配 _meta.team_members"""
    from organization.model import OrganizationModel
    org = OrganizationModel()
    members = org.get_members("李林骁")
    assert len(members) == 5, f"期望 5 名成员，实际 {len(members)}: {members}"
    assert "张志斌" in members
    assert "杨梦卓" in members
    assert "苗笑天" in members
    assert "谭继衡" in members
    assert "陈红洁" in members


def test_org_ssot_no_outsiders():
    """外部人员（如王亮、程智）不应出现在团队成员中"""
    from organization.model import OrganizationModel
    org = OrganizationModel()
    members = org.get_members("李林骁")
    for outsider in ["王亮", "程智", "郝晓平", "荆幸斌"]:
        assert outsider not in members, f"{outsider} 不应是团队成员"


def test_org_ssot_leader_lookup():
    """get_leader 应返回正确工班长"""
    from organization.model import OrganizationModel
    org = OrganizationModel()
    assert org.get_leader("陈红洁") == "李林骁"
    assert org.get_leader("苗笑天") == "李林骁"
    assert org.get_leader("王亮") == ""   # 外部人员无 leader


def test_org_ssot_team_name():
    """get_team_name 返回铁炉西工班"""
    from organization.model import OrganizationModel
    org = OrganizationModel()
    assert org.get_team_name("李林骁") == "铁炉西工班"


# ── 2. MCP Server ──


def test_mcp_initialize():
    """MCP initialize 握手返回正确协议版本"""
    from memory.memory_server import handle
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    resp = handle(req)
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "memory"


def test_mcp_tools_list():
    """MCP tools/list 返回 4 个工具"""
    from memory.memory_server import handle
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = handle(req)
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "memory_search" in names
    assert "memory_save" in names
    assert "knowledge_retrieve" in names
    assert "memory_reflect" in names
    assert len(tools) == 4


def test_mcp_unknown_method():
    """未知方法返回 error"""
    from memory.memory_server import handle
    req = {"jsonrpc": "2.0", "id": 3, "method": "unknown_method"}
    resp = handle(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601
