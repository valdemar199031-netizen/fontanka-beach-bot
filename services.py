from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

WMO = {
    0: ("☀️", "Ясно"), 1: ("🌤", "Преимущественно ясно"), 2: ("⛅", "Переменная облачность"), 3: ("☁️", "Облачно"),
    45: ("🌫", "Туман"), 48: ("🌫", "Изморозь/туман"), 51: ("🌦", "Морось"), 53: ("🌦", "Морось"), 55: ("🌧", "Сильная морось"),
    61: ("🌧", "Небольшой дождь"), 63: ("🌧", "Дождь"), 65: ("🌧", "Сильный дождь"), 71: ("🌨", "Небольшой снег"), 73: ("🌨", "Снег"),
    75: ("❄️", "Сильный снег"), 80: ("🌦", "Ливневый дождь"), 81: ("🌧", "Ливневый дождь"), 82: ("⛈", "Сильный ливень"),
    95: ("⛈", "Гроза"), 96: ("⛈", "Гроза с градом"), 99: ("⛈", "Сильная гроза с градом"),
}


@dataclass
class FontankaData:
    air_temp: float
    feels_like: float
    wind_speed: float
    wind_dir: float | None
    wind_gusts: float
    humidity: int
    precip_prob: int
    weather_code: int
    weather_emoji: str
    weather_desc: str
    sunrise: str
    sunset: str
    water_temp: float | None
    wave_height: float | None
    wave_dir: float | None
    alerts: list[str]
    beach_rating: str
    sea_rating: str
    daily: list[dict[str, Any]]


class WeatherService:
    def __init__(self, lat: float, lon: float, tz: ZoneInfo):
        self.lat = lat
        self.lon = lon
        self.tz = tz
        self._cache: tuple[datetime, FontankaData] | None = None

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    async def current(self) -> FontankaData:
        now = datetime.now(self.tz)
        if self._cache and now - self._cache[0] < timedelta(minutes=5):
            return self._cache[1]
        weather_params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "timezone": "auto",
            "forecast_days": 7,
            "wind_speed_unit": "ms",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "hourly": "precipitation_probability",
            "daily": "weather_code,sunrise,sunset,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max",
        }
        marine_params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "timezone": "auto",
            "forecast_days": 7,
            "current": "wave_height,wave_direction,sea_surface_temperature",
            "daily": "wave_height_max",
        }
        weather_data, marine_data = await self._parallel(weather_params, marine_params)
        c = weather_data["current"]
        m = marine_data.get("current", {})
        code = int(c.get("weather_code", 0))
        emoji, desc = WMO.get(code, ("🌤", "Переменная погода"))

        hourly_times = weather_data.get("hourly", {}).get("time", [])
        hourly_probs = weather_data.get("hourly", {}).get("precipitation_probability", [])
        precip_prob = int(hourly_probs[0]) if hourly_probs else 0

        daily = []
        d = weather_data.get("daily", {})
        for i, date in enumerate(d.get("time", [])):
            dc = int(d["weather_code"][i])
            e, _ = WMO.get(dc, ("🌤", ""))
            daily.append({
                "date": date[5:], "emoji": e,
                "tmax": float(d["temperature_2m_max"][i]), "tmin": float(d["temperature_2m_min"][i]),
                "rain": float(d["precipitation_probability_max"][i]), "wind": float(d["wind_speed_10m_max"][i]),
            })

        water = m.get("sea_surface_temperature")
        wave = m.get("wave_height")
        wave_dir = m.get("wave_direction")
        wind_speed = float(c.get("wind_speed_10m", 0))
        gusts = float(c.get("wind_gusts_10m", 0))
        alerts = build_alerts(code, wind_speed, gusts, wave, precip_prob, water)
        sea_rating = sea_condition(wind_speed, wave)
        beach_rating = beach_condition(code, wind_speed, wave, precip_prob)

        result = FontankaData(
            air_temp=float(c.get("temperature_2m", 0)),
            feels_like=float(c.get("apparent_temperature", 0)),
            wind_speed=wind_speed,
            wind_dir=float(c.get("wind_direction_10m", 0)),
            wind_gusts=gusts,
            humidity=int(c.get("relative_humidity_2m", 0)),
            precip_prob=precip_prob,
            weather_code=code,
            weather_emoji=emoji,
            weather_desc=desc,
            sunrise=fmt_time(d.get("sunrise", [""])[0]),
            sunset=fmt_time(d.get("sunset", [""])[0]),
            water_temp=float(water) if water is not None else None,
            wave_height=float(wave) if wave is not None else None,
            wave_dir=float(wave_dir) if wave_dir is not None else None,
            alerts=alerts,
            beach_rating=beach_rating,
            sea_rating=sea_rating,
            daily=daily,
        )
        self._cache = (now, result)
        return result

    async def forecast7(self) -> FontankaData:
        return await self.current()

    async def _parallel(self, wp: dict[str, Any], mp: dict[str, Any]):
        return await __import__("asyncio").gather(self._get(WEATHER_URL, wp), self._get(MARINE_URL, mp))


def fmt_time(value: str) -> str:
    return value[-5:] if value and "T" in value else (value or "—")


def build_alerts(code: int, wind: float, gust: float, wave: float | None, precip_prob: int, water: float | None) -> list[str]:
    out: list[str] = []
    if code in (95, 96, 99):
        out.append("⛈ Возможна гроза — на открытом пляже лучше не находиться во время грозы.")
    if gust >= 17 or wind >= 14:
        out.append(f"💨 Сильный ветер: до {max(gust, wind):.1f} м/с.")
    if wave is not None and wave >= 1.2:
        out.append(f"🌊 Волнение моря повышено: волна около {wave:.1f} м.")
    if precip_prob >= 75:
        out.append(f"☔ Высокая вероятность осадков: {precip_prob}%.")
    if water is not None and water < 16:
        out.append(f"🥶 Вода прохладная: около {water:.1f}°C.")
    return out


def sea_condition(wind: float, wave: float | None) -> str:
    if wave is None:
        return "Состояние моря: данные о волне временно недоступны."
    if wave < 0.3 and wind < 5:
        return "🏊 Море спокойное — хорошие условия для купания."
    if wave < 0.7 and wind < 9:
        return "🏊 Море умеренное — для большинства отдыхающих комфортно."
    if wave < 1.2 and wind < 14:
        return "⚠️ Море заметно волнуется — купание с осторожностью."
    return "🚨 Сильное волнение — купание лучше отложить."


def beach_condition(code: int, wind: float, wave: float | None, rain: int) -> str:
    if code in (95, 96, 99):
        return "⛔ Пляж сейчас не рекомендуется из-за грозовой активности."
    if rain >= 80:
        return "🌧 Для пляжа условия слабые: высокая вероятность дождя."
    if (wave is not None and wave >= 1.2) or wind >= 14:
        return "⚠️ Для пляжа условия сложные: сильный ветер или заметное волнение."
    return "✅ Для пляжа условия хорошие."
