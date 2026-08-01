"""
weather_query.py — 天气查询工具（确定性规则，不用 LLM）。

数据源（多源交叉验证，重点降雨）：
  1. 中国天气网官方 d1.weather.com.cn — 实时 rain/rain24h + 今日天气描述
  2. Open-Meteo (ECMWF/GFS) — 未来7天降雨毫米 + 降雨概率
  3. itboy 聚合（中国天气网城市代码）— 15天天气类型描述

默认城市：郑州（101180101）。其他城市需在 CITY_MAP 中有代码。
"""
import json
import logging
import time
import urllib.request

logger = logging.getLogger(__name__)

# 城市代码映射（中国天气网城市代码）。默认郑州。
CITY_MAP = {
    "郑州": "101180101",
    "郑州中原区": "101180101",
    "中原区": "101180101",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280101",
    "深圳": "101280601",
    "天津": "101030100",
    "重庆": "101040100",
    "武汉": "101200101",
    "西安": "101110101",
    "成都": "101270101",
    "杭州": "101210101",
    "南京": "101190101",
    "济南": "101120101",
    "洛阳": "101180901",
    "开封": "101180801",
    "长沙": "101250101",
    "沈阳": "101070101",
    "青岛": "101120201",
    "苏州": "101190401",
}

# 郑州坐标（Open-Meteo 使用）
CITY_COORDS = {
    "101180101": (34.7466, 113.6254),   # 郑州
    "101010100": (39.9042, 116.4074),   # 北京
    "101020100": (31.2304, 121.4737),   # 上海
    "101280101": (23.1291, 113.2644),   # 广州
    "101280601": (22.5431, 114.0579),   # 深圳
    "101030100": (39.3434, 117.3616),   # 天津
    "101040100": (29.5630, 106.5516),   # 重庆
    "101200101": (30.5928, 114.3055),   # 武汉
    "101110101": (34.3416, 108.9398),   # 西安
    "101270101": (30.5728, 104.0668),   # 成都
    "101210101": (30.2741, 120.1551),   # 杭州
    "101190101": (32.0603, 118.7969),   # 南京
    "101120101": (36.6512, 117.1201),   # 济南
    "101180901": (34.6181, 112.4540),   # 洛阳
    "101180801": (34.7973, 114.3073),   # 开封
    "101250101": (28.2282, 112.9388),   # 长沙
    "101070101": (41.8057, 123.4315),   # 沈阳
    "101120201": (36.0671, 120.3826),   # 青岛
    "101190401": (31.2989, 120.5853),   # 苏州
}

_DEFAULT_COORDS = (34.7466, 113.6254)

# 缓存：{city_code: (fetch_time, result)}
_CACHE = {}
CACHE_TTL = 1800  # 30 分钟


def _fetch(url: str, timeout: int = 8) -> str:
    """抓取 URL 文本。失败返回空串，不抛异常。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "Referer": "https://www.weather.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("weather fetch failed %s: %s", url[:60], e)
        return ""


def _fetch_weather(city_code: str) -> dict:
    """抓取三源数据并返回原始 dict。测试可直接 patch 本函数。"""
    now = time.time()
    cached = _CACHE.get(city_code)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    result = {"city": city_code, "sources": {}}

    # 源1: 中国天气网官方实时 + 今日
    raw = _fetch(f"http://d1.weather.com.cn/weather_index/{city_code}.html?_={int(now*1000)}")
    src1 = {}
    for var in ("dataSK", "cityDZ"):
        start = raw.find(var + " ={")
        if start == -1:
            start = raw.find(var + " = {")
        if start == -1:
            continue
        start = raw.find("{", start)
        end = raw.find("};", start)
        if start == -1 or end == -1:
            continue
        try:
            src1[var] = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    if src1:
        result["sources"]["d1"] = src1

    # 源2: Open-Meteo 7天降雨
    lat, lon = CITY_COORDS.get(city_code, _DEFAULT_COORDS)
    url2 = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&daily=precipitation_sum,precipitation_probability_max,weathercode"
        ",temperature_2m_max,temperature_2m_min&timezone=Asia%2FShanghai&forecast_days=7"
    )
    raw2 = _fetch(url2)
    if raw2:
        try:
            result["sources"]["openmeteo"] = json.loads(raw2)
        except json.JSONDecodeError:
            pass

    # 源3: itboy 15天类型
    raw3 = _fetch(f"http://t.weather.itboy.net/api/weather/city/{city_code}")
    if raw3:
        try:
            result["sources"]["itboy"] = json.loads(raw3)
        except json.JSONDecodeError:
            pass

    _CACHE[city_code] = (now, result)
    return result


_RAIN_KW = ("雨", "雷", "雪", "雹")


def _is_rain_type(weather_type: str) -> bool:
    return any(kw in (weather_type or "") for kw in _RAIN_KW)


def _format_weather(data: dict) -> str:
    """合并三源为结构化文本。确定性规则，不用 LLM。"""
    city = data.get("city", "")
    sources = data.get("sources", {})
    city_name = next((n for n, c in CITY_MAP.items() if c == city), "该城市")
    lines = [f"📍 {city_name} 天气（多源交叉验证）"]

    # --- 实时（源1 d1）---
    sk = (sources.get("d1") or {}).get("dataSK") or {}
    dz = (sources.get("d1") or {}).get("cityDZ") or {}
    if sk:
        temp = sk.get("temp", "?")
        humidity = sk.get("SD") or sk.get("sd", "?")
        rain_now = sk.get("rain", "?")
        rain_24h = sk.get("rain24h", "?")
        wind = sk.get("WD", "")
        wind_scale = sk.get("WS", "")
        lines.append(f"实时：{temp}℃，湿度 {humidity}，风 {wind}{wind_scale}")
        try:
            if float(rain_24h or 0) > 0:
                lines.append(f"近24小时降雨 {rain_24h} 毫米")
        except (TypeError, ValueError):
            pass
    if dz:
        dz_w = dz.get("weather", "")
        if dz_w:
            lines.append(f"今日天气：{dz_w}")

    # --- 7天降雨（源2 openmeteo）---
    om = sources.get("openmeteo") or {}
    daily = om.get("daily") or {}
    dates = daily.get("time") or []
    rains = daily.get("precipitation_sum") or []
    probs = daily.get("precipitation_probability_max") or []
    codes = daily.get("weathercode") or []
    tmax = daily.get("temperature_2m_max") or []

    if dates:
        has_rain_days = 0
        rain_detail = []
        for i, d in enumerate(dates):
            r = rains[i] if i < len(rains) else 0
            p = probs[i] if i < len(probs) else 0
            t = tmax[i] if i < len(tmax) else "?"
            day_name = "今天" if i == 0 else ("明天" if i == 1 else d[5:])
            mark = ""
            if r > 0 or p >= 50:
                has_rain_days += 1
                mark = "⚠️ 有雨"
            elif p >= 30:
                mark = "☁️ 可能降雨"
            else:
                mark = "☀️ 无雨"
            rain_detail.append(f"{day_name}: {mark}（降雨 {r} 毫米/概率 {p}%）")
        lines.append(f"未来{len(dates)}天降雨：{has_rain_days} 天有雨")
        lines.append("  " + "；".join(rain_detail[:5]))

    # --- 15天类型（源3 itboy）---
    itb = sources.get("itboy") or {}
    fc = (itb.get("data") or {}).get("forecast") or []
    if fc:
        rain_days = []
        for f in fc:
            if _is_rain_type(f.get("type", "")):
                rain_days.append(f"{f.get('ymd', '?')[5:]}({f.get('type', '雨')})")
        if rain_days:
            lines.append(f"15天预报中降雨日：{', '.join(rain_days[:6])}")
        else:
            lines.append("15天预报暂无降雨日")

    # --- 综合判断 ---
    if om.get("daily") and dates:
        nearest_rain = None
        for i, d in enumerate(dates):
            r = rains[i] if i < len(rains) else 0
            p = probs[i] if i < len(probs) else 0
            if r > 0 or p >= 60:
                day_name = "今天" if i == 0 else ("明天" if i == 1 else d[5:])
                nearest_rain = f"{day_name}（降雨{r}毫米，概率{p}%）"
                break
        if nearest_rain:
            lines.append(f"💧 最近降雨：{nearest_rain}")
        else:
            lines.append("未来7天无明显降雨，无需带伞")

    if len(sources) < 2:
        lines.append("（部分数据源不可用，以上结果仅供参考）")

    return "\n".join(lines)


def handle(user_input, ctx=None) -> str:
    """入口。user_input 为城市名或城市代码，默认郑州。"""
    text = (user_input or "").strip()
    city_code = CITY_MAP.get(text) or next(
        (c for c in CITY_MAP.values() if text in c or text in str(c)), None
    )
    if not city_code:
        city_code = CITY_MAP.get("郑州", "101180101")

    data = _fetch_weather(city_code)
    if not data.get("sources"):
        return "[Cipher] 天气服务暂不可用，请稍后再试。"

    return f"[Cipher:weather]\n{_format_weather(data)}"


if __name__ == "__main__":
    print(handle("郑州"))
