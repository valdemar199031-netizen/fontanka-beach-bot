import os
import asyncio
import random
from datetime import datetime
from zoneinfo import ZoneInfo

# Заменили синхронный requests на асинхронный httpx, чтобы бот не зависал
import httpx

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# НАСТРОЙКИ
# ============================================================

# Все токены и ID теперь безопасно берутся из панели Zeabur
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

LAT = 46.56
LON = 30.86

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# ============================================================
# АСИНХРОННАЯ ПОГОДА
# ============================================================

async def get_weather():
    url = "https://open-meteo.com"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "timezone": "Europe/Kyiv",
        "forecast_days": 1,
    }
    # Используем асинхронный клиент httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

def weather_name(code):
    names = {
        0: "☀️ Ясно", 1: "🌤 Преимущественно ясно", 2: "⛅ Переменная облачность", 3: "☁️ Пасмурно",
        45: "🌫 Туман", 48: "🌫 Туман",
        51: "🌦 Небольшая морось", 53: "🌦 Морось", 55: "🌧 Сильная морось",
        61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
        71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "❄️ Сильный снег",
        80: "🌦 Ливневый дождь", 81: "🌧 Ливни", 82: "⛈ Сильные ливни",
        95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Сильная гроза с градом",
    }
    return names.get(code, "🌤 Переменная погода")

async def weather_text():
    # Функция стала асинхронной, чтобы не блокировать процесс бота
    data = await get_weather()
    current = data["current"]
    daily = data["daily"]

    temperature = round(current["temperature_2m"])
    feels = round(current["apparent_temperature"])
    humidity = current["relative_humidity_2m"]
    wind = round(current["wind_speed_10m"])
    
    # Исправлено извлечение элементов из списков Open-Meteo
    minimum = round(daily["temperature_2m_min"][0])
    maximum = round(daily["temperature_2m_max"][0])
    condition = weather_name(current["weather_code"])

    return (
        "🏖 <b>ФОНТАНКА — ПОГОДА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{condition}\n\n"
        f"🌡 Сейчас: <b>{temperature}°C</b>\n"
        f"🤚 Ощущается как: <b>{feels}°C</b>\n"
        f"📈 Сегодня: <b>{minimum}°C — {maximum}°C</b>\n"
        f"💨 Ветер: <b>{wind} км/ч</b>\n"
        f"💧 Влажность: <b>{humidity}%</b>\n\n"
        "🌊 <i>Хорошего отдыха у моря!</i>"
    )

# ============================================================
# АСИНХРОННОЕ МОРЕ
# ============================================================

async def get_sea():
    url = "https://open-meteo.com"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "sea_surface_temperature,wave_height",
        "timezone": "Europe/Kyiv",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

async def sea_values():
    data = await get_sea()
    current = data["current"]

    water = current.get("sea_surface_temperature")
    waves = current.get("wave_height")

    water_text = "нет данных" if water is None else f"{round(water, 1)}°C"
    waves_text = "нет данных" if waves is None else f"{round(waves, 1)} м"

    return water_text, waves_text

# ============================================================
# ДАННЫЕ (ФАКТЫ И СОВЕТЫ)
# ============================================================

FACTS = [
    "📖 Fontanka находится в Одесском районе Одесской области.",
    "🌊 Fontanka расположена на берегу Чёрного моря.",
    "🏖 Fontanka находится совсем рядом с Одессой.",
    "🌅 С побережья можно наблюдать красивые морские закаты.",
    "🌊 Температура воды меняется медленнее температуры воздуха.",
    "💨 При усилении ветра состояние моря может быстро измениться.",
    "☀️ Летом побережье Фонтанки становится популярным местом отдыха.",
    "🌊 Чёрное море — главная природная особенность побережья Фонтанки.",
    "🌅 Утром море часто выглядит спокойнее, чем при усилении дневного ветра.",
    "📸 Морское побережье Фонтанки часто становится местом прогулок и фотографий.",
    "🌊 В безветренную погоду поверхность моря может становиться практически зеркальной.",
    "💨 Морской ветер способен заметно менять ощущаемую температуру.",
    "🏡 Фонтанка сочетает частную застройку и современные жилые комплексы.",
    "🏖 Близость к Одессе делает Фонтанку удобным местом для отдыха у моря.",
    "🌿 В окрестностях побережья встречается степная растительность.",
    "😎 Фонтанка позволяет совместить близость города и атмосферу морского отдыха."
]

TIPS = [
    "☀️ Используйте солнцезащитный крем даже при лёгкой облачности.",
    "💧 В жаркую погоду обязательно берите с собой воду.",
    "🕶 Солнцезащитные очки пригодятся даже утром.",
    "🧴 После купания обновляйте солнцезащитный крем.",
    "🎒 На пляж пригодятся вода, полотенце, крем, очки и головной убор.",
    "🌊 Перед купанием обращайте внимание на состояние моря.",
    "💨 При сильном ветре возле моря может ощущаться прохладнее.",
    "🌅 Для спокойной прогулки отлично подходят утренние и вечерние часы.",
    "🌊 При сильном волнении не переоценивайте свои силы.",
    "📱 Не оставляйте ценные вещи без присмотра.",
    "😎 Хороший пляжный день начинается с воды, крема и хорошего настроения."
]

# ============================================================
# ОБРАБОТЧИКИ КОМАНД (TELEGRAM HANDLERS)
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏖 <b>FONTANKA BEACH</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🌊 <b>Твой помощник у моря</b>\n\n"
        "🌤 <b>ПОГОДА</b>\n/weather — текущая погода\n\n"
        "🌊 <b>МОРЕ</b>\n/sea — температура воды и волны\n\n"
        "🏖 <b>ОТДЫХ</b>\n/today — погода + море\n/beach — пляжный чек\n\n"
        "📖 <b>ФОНТАНКА</b>\n/fact — интересный факт\n/tip — совет отдыхающим\n\n"
        "🆔 /chatid — ID группы\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "☀️ <i>Море ближе, чем кажется.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await weather_text()
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        print("WEATHER ERROR:", e)
        await update.message.reply_text("⚠️ Не удалось получить погоду.")

async def sea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        water, waves = await sea_values()
        text = (
            "🌊 <b>МОРЕ — ФОНТАНКА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🌡 Температура воды: <b>{water}</b>\n"
            f"〰️ Высота волн: <b>{waves}</b>\n\n"
            "🏖 <i>Хорошего отдыха у моря!</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        print("SEA ERROR:", e)
        await update.message.reply_text("⚠️ Не удалось получить данные о море.")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await get_weather()
        water, waves = await sea_values()

        current = data["current"]
        daily = data["daily"]

        temperature = round(current["temperature_2m"])
        feels = round(current["apparent_temperature"])
        minimum = round(daily["temperature_2m_min"][0])
        maximum = round(daily["temperature_2m_max"][0])
        wind = round(current["wind_speed_10m"])
        humidity = current["relative_humidity_2m"]
        condition = weather_name(current["weather_code"])

        text = (
            "🏖 <b>ФОНТАНКА — СЕГОДНЯ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{condition}\n\n"
            "🌤 <b>ПОГОДА</b>\n"
            f"🌡 Воздух: <b>{temperature}°C</b>\n"
            f"🤚 Ощущается: <b>{feels}°C</b>\n"
            f"📈 Сегодня: <b>{minimum}°C — {maximum}°C</b>\n"
            f"💨 Ветер: <b>{wind} км/ч</b>\n"
            f"💧 Влажность: <b>{humidity}%</b>\n\n"
            "🌊 <b>МОРЕ</b>\n"
            f"🌡 Вода: <b>{water}</b>\n"
            f"〰️ Волны: <b>{waves}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "😎 <i>Самое время к морю!</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        print("TODAY ERROR:", e)
        await update.message.reply_text("⚠️ Не удалось собрать данные.")

async def fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>ФАКТ О ФОНТАНКЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{random.choice(FACTS)}\n\n"
        "🏖 <i>Фонтанка — море рядом с Одессой.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 <b>СОВЕТ ОТ FONTANKA BEACH</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{random.choice(TIPS)}\n\n"
        "🌊 <i>Берегите себя и наслаждайтесь морем.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def beach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await get_weather()
        water, waves = await sea_values()
