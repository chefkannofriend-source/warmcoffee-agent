"""
温湿度获取：API → 传感器 → 手动输入（三路选择）
"""

import json
import os
from datetime import date, timedelta


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
WEATHER_CACHE = os.path.join(DATA_DIR, "weather_cache.json")
WEATHER_CONFIG = os.path.join(DATA_DIR, "weather_config.json")


def fetch_weather_api(api_key: str, location: str) -> dict:
    """
    通过 OpenWeatherMap API 获取当前温湿度。
    返回 {"temp": float, "humidity": float, "source": "api"}
    """
    try:
        import urllib.request
        import urllib.parse
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.parse.quote(location)}&appid={api_key}&units=metric"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        temp = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        result = {"temp": round(temp, 1), "humidity": humidity, "source": "api"}
        _cache_weather(result)
        return result
    except Exception as e:
        raise RuntimeError(f"API 获取失败：{e}")


def load_sensor_data(device_config: dict) -> dict:
    """
    传感器数据接入（预留接口）。
    device_config: {"type": "mqtt"|"serial", ...}
    返回 {"temp": float, "humidity": float, "source": "sensor"}
    """
    raise NotImplementedError("传感器接入尚未配置。请在 device_config 中指定设备参数。")


def manual_input() -> dict:
    """交互式手动输入温湿度"""
    while True:
        try:
            temp = float(input("请输入当前温度（°C）：").strip())
            humidity = float(input("请输入当前湿度（%）：").strip())
            result = {"temp": temp, "humidity": humidity, "source": "manual"}
            _cache_weather(result)
            return result
        except ValueError:
            print("请输入数字")


def _cache_weather(data: dict) -> None:
    """写入今日缓存"""
    cache = _load_cache()
    cache[date.today().isoformat()] = data
    # 只保留最近 7 天
    keys = sorted(cache.keys())[-7:]
    cache = {k: cache[k] for k in keys}
    with open(WEATHER_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _load_cache() -> dict:
    if not os.path.exists(WEATHER_CACHE):
        return {}
    with open(WEATHER_CACHE, encoding="utf-8") as f:
        return json.load(f)


def _load_config() -> dict:
    """读取持久化的 API 配置"""
    if not os.path.exists(WEATHER_CONFIG):
        return {}
    with open(WEATHER_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    """保存 API 配置到文件"""
    with open(WEATHER_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def setup_weather_source() -> dict:
    """
    首次或手动触发的数据源配置向导。
    返回配置 dict，同时写入 weather_config.json。
    """
    print("\n── 温湿度数据来源配置 ──")
    print("1. OpenWeatherMap API（自动获取，需要免费 API Key）")
    print("2. 手动输入（每次 session 手动填写）")
    print("3. 跳过（使用昨日估算值，置信度降低）")

    choice = input("请选择 [1/2/3]：").strip()

    config = {}

    if choice == "1":
        print("\nOpenWeatherMap 免费 API：https://openweathermap.org/api")
        print("注册后在 My API keys 页面获取 Key。")
        api_key = input("请输入 API Key：").strip()
        location = input("请输入城市（英文，如 Shanghai 或 Hong Kong）：").strip()
        if api_key and location:
            # 测试连通性
            print("正在验证 API Key...")
            try:
                result = fetch_weather_api(api_key, location)
                print(f"✓ 连接成功：{result['temp']}°C，湿度 {result['humidity']}%")
                config = {"source": "api", "api_key": api_key, "location": location}
                _save_config(config)
                print("✓ 配置已保存，后续 session 自动获取天气数据。")
                return result
            except RuntimeError as e:
                print(f"✗ 验证失败：{e}")
                print("已退回手动输入模式。")
        config = {"source": "manual"}
        _save_config(config)
        return manual_input()

    elif choice == "2":
        config = {"source": "manual"}
        _save_config(config)
        return manual_input()

    else:
        config = {"source": "skip"}
        _save_config(config)
        cache = _load_cache()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if yesterday in cache:
            est = cache[yesterday].copy()
            est["source"] = "estimated"
            est["note"] = "环境数据估算（使用昨日数值），置信度降低"
            print(f"⚠️  {est['note']}")
            return est
        print("⚠️  无昨日数据，使用默认值（20°C / 60%），置信度降低。")
        return {"temp": 20.0, "humidity": 60.0, "source": "estimated",
                "note": "环境数据使用默认值，置信度降低"}


def get_env_data(api_key: str = None, location: str = None, device_config: dict = None) -> dict:
    """
    三路选择逻辑：
    1. 优先读取持久化配置（weather_config.json）
    2. 命令行参数传入的 api_key/location
    3. 无任何配置时，触发配置向导让用户选择
    """
    # 读取已保存的配置
    saved_config = _load_config()

    # 命令行参数优先级最高
    if api_key and location:
        try:
            return fetch_weather_api(api_key, location)
        except RuntimeError as e:
            print(f"⚠️  API 获取失败：{e}")

    # 使用已保存的 API 配置
    if saved_config.get("source") == "api":
        try:
            return fetch_weather_api(saved_config["api_key"], saved_config["location"])
        except RuntimeError as e:
            print(f"⚠️  API 获取失败：{e}，退回手动输入")
            return manual_input()

    # 已配置为手动输入
    if saved_config.get("source") == "manual":
        return manual_input()

    # 已配置为跳过：使用昨日缓存
    if saved_config.get("source") == "skip":
        cache = _load_cache()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if yesterday in cache:
            est = cache[yesterday].copy()
            est["source"] = "estimated"
            est["note"] = "环境数据估算（使用昨日数值），置信度降低"
            print(f"⚠️  {est['note']}")
            return est
        print("⚠️  无昨日数据，使用默认值（20°C / 60%）")
        return {"temp": 20.0, "humidity": 60.0, "source": "estimated",
                "note": "环境数据使用默认值，置信度降低"}

    # 传感器（预留）
    if device_config:
        try:
            return load_sensor_data(device_config)
        except NotImplementedError:
            pass

    # 首次使用：无任何配置，触发向导
    print("\n尚未配置温湿度数据来源。")
    return setup_weather_source()
