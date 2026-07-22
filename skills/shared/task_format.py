import re
from datetime import datetime, timedelta

LOCATIONS = [
    "铁炉西", "城南", "关陈", "郑东", "红石坡", "贾峪", "圃田",
    "中州大道", "中州", "杂品库", "消防档案", "物资调配室",
]

CATEGORY_RULES = [
    (r"危废|废旧|联单|处置", "危废"),
    (r"应急|消防|预案|安全|灭火器|电源线", "安全"),
    (r"物资|电源线|库房|物资检查", "物资"),
    (r"特种|复审|证件|控制柜|风机", "设备"),
    (r"铁屑|废料|中州大道", "废料"),
    (r"自查|整改|39条", "整改"),
]


def categorize(text):
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, text):
            return cat
    return "管理"


def extract_location(text):
    found = []
    for loc in sorted(LOCATIONS, key=len, reverse=True):
        if loc in text:
            if not any(loc in f for f in found):
                found.append(loc)
    return "/".join(found)


def _clean_summary(text):
    text = re.sub(r"（[^）]*）", "", text)
    for loc in sorted(LOCATIONS, key=len, reverse=True):
        text = text.replace(loc, "")
    text = re.sub(r"[和及与]($|[，。；、])", r"\1", text)
    text = re.sub(r"，[^，。]+$", "", text)
    text = re.sub(r"^[：:，。；、\s]+", "", text)
    text = re.sub(r"[：:，。；、\s]+$", "", text)
    return text


def format_deadline(deadline_str):
    if not deadline_str:
        return ""
    try:
        dt = datetime.fromisoformat(deadline_str)
    except Exception:
        return ""
    now = datetime.now()
    today = now.date()
    dt_date = dt.date()
    time_str = dt.strftime("%H:%M")
    if dt_date == today:
        return f"今{time_str}"
    elif dt_date == today + timedelta(days=1):
        return f"明{time_str}"
    elif dt_date == today - timedelta(days=1):
        return f"昨{time_str}"
    else:
        return dt.strftime("%m/%d %H:%M")


def build_title(summary, raw_text="", deadline=""):
    text = raw_text or summary or ""
    cat = categorize(text)
    loc = extract_location(text)
    time_str = format_deadline(deadline)

    clean = _clean_summary(summary or text)
    for prefix in ["完成", "进行", "做好", "组织", "督促", "通知", "安排", "要求"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].lstrip("一下：:：，。；、 ")
            break

    if len(clean) > 25:
        cut = clean[:25]
        lasts = [cut.rfind(p) for p in "，；。" if p in cut]
        last_punc = max(lasts) if lasts else -1
        if last_punc > 5:
            clean = cut[:last_punc]
        else:
            clean = cut
    clean = clean.rstrip("，。；、")

    if not clean or len(clean) < 2:
        clean = "相关任务"

    title = f"【{cat}】{clean}"
    if loc:
        title += f" {loc}"
    if time_str:
        title += f" {time_str}"
    return title
