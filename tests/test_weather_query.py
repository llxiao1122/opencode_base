"""test_weather_query.py — weather_query 工具测试。

patch _fetch_weather 避免真实网络调用（conftest 全局 mock 了 urllib）。
"""
from unittest.mock import patch

from skills.agent.handlers.weather_query import handle, _format_weather, _is_rain_type


def _mock_weather_data(city="101180101", sources_full=True):
    sources = {}
    if sources_full:
        sources["d1"] = {
            "dataSK": {"temp": "31.1", "SD": "73%", "rain": "0", "rain24h": "0",
                       "WD": "北风", "WS": "1级"},
            "cityDZ": {"weather": "多云转小雨"},
        }
        sources["openmeteo"] = {
            "daily": {
                "time": ["2026-08-01", "2026-08-02", "2026-08-03"],
                "precipitation_sum": [5.2, 0.0, 0.0],
                "precipitation_probability_max": [80, 20, 10],
                "weathercode": [96, 3, 3],
                "temperature_2m_max": [33.0, 32.0, 31.0],
                "temperature_2m_min": [26.0, 25.0, 24.0],
            }
        }
        sources["itboy"] = {
            "data": {"forecast": [
                {"ymd": "2026-08-01", "type": "小雨"},
                {"ymd": "2026-08-02", "type": "多云"},
                {"ymd": "2026-08-03", "type": "晴"},
            ]}
        }
    return {"city": city, "sources": sources}


def test_weather_normal_rain_report():
    with patch("skills.agent.handlers.weather_query._fetch_weather",
               return_value=_mock_weather_data()):
        result = handle("郑州")
    assert result.startswith("[Cipher:weather]")
    assert "郑州" in result
    assert "未来" in result
    assert "有雨" in result
    assert "降雨" in result


def test_weather_no_rain():
    data = _mock_weather_data()
    # 全无雨
    data["sources"]["openmeteo"]["daily"]["precipitation_sum"] = [0.0, 0.0, 0.0]
    data["sources"]["openmeteo"]["daily"]["precipitation_probability_max"] = [10, 5, 5]
    with patch("skills.agent.handlers.weather_query._fetch_weather", return_value=data):
        result = handle("郑州")
    assert "无明显降雨" in result


def test_weather_source_unavailable():
    with patch("skills.agent.handlers.weather_query._fetch_weather",
               return_value=_mock_weather_data(sources_full=False)):
        result = handle("郑州")
    assert "暂不可用" in result


def test_weather_default_city():
    with patch("skills.agent.handlers.weather_query._fetch_weather",
               return_value=_mock_weather_data()) as mock_fetch:
        handle("")
    assert mock_fetch.call_args[0][0] == "101180101"  # 默认郑州


def test_weather_unknown_city_falls_back_to_zhengzhou():
    with patch("skills.agent.handlers.weather_query._fetch_weather",
               return_value=_mock_weather_data()) as mock_fetch:
        handle("火星")
    assert mock_fetch.call_args[0][0] == "101180101"


def test_is_rain_type():
    assert _is_rain_type("小雨")
    assert _is_rain_type("雷阵雨")
    assert not _is_rain_type("晴")
    assert not _is_rain_type("多云")
