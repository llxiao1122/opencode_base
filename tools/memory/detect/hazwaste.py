"""
memory/detect/hazwaste.py — Hazard waste (危废) specific business rules.

Consolidated rules for hazardous waste disposal operations.
"""

_HAZWASTE_CONSTRAINTS = [
    "须佩戴执法记录仪全程录像",
    "须确认车辆信息与联单派遣信息一致",
    "须签署《外来人员安全告知书》并登记",
    "须2名工班人员用校准过的称重工具共同核对重量",
    "双方须在i物资上签字确认后才可装车",
    "须拍摄装车前、装车后带水印照片（各≥2张）发钉钉群",
    "处置完成后须在OA流程上及时办理",
    "须2个工作日内完成台账更新",
]

_HAZWASTE_TASKS = [
    "确认处置单据对应的OA单号",
    "确认处置车辆进段场前信息一致性（车牌号与联单）",
    "对处置单位人员进行安全交底，签署《外来人员安全告知书》",
    "2名工班人员用校准过的称重工具与处置单位共同核对重量",
    "双方在i物资上签字确认",
    "全程佩戴执法记录仪，网盘留存录像",
    "拍摄装车前、装车后带水印照片各≥2张，发钉钉工作群",
    "处置完成后在OA流程上及时办理",
    "2个工作日内完成台账更新",
    "每月30日前将处置单据移交模块责任人",
]


def _enrich_hazwaste(event, text):
    if not any(kw in text for kw in ["危废", "危险废物"]):
        return event
    existing_actions = event.get("required_actions", [])
    for t in _HAZWASTE_TASKS:
        if t not in existing_actions:
            existing_actions.append(t)
    existing_constraints = event.get("constraints", [])
    for c in _HAZWASTE_CONSTRAINTS:
        if c not in existing_constraints:
            existing_constraints.append(c)
    event["required_actions"] = existing_actions
    event["constraints"] = existing_constraints
    return event
