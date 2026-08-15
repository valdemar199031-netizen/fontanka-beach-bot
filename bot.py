import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from content import FACTS, BEACH_TIPS
from services import FontankaData, WeatherService
from photos import wikimedia_photo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("fontanka")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
CHAT_ID_ENV = os.getenv("CHAT_ID", "").strip()
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))

# Автоматические публикации: 09:00, 14:00, 19:00.
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "9"))
AFTERNOON_HOUR = int(os.getenv("AFTERNOON_HOUR", "14"))
EVENING_HOUR = int(os.getenv("EVENING_HOUR", "19"))

# Это только частота проверки расписания/предупреждений.
# Погода НЕ запрашивается каждые 30/60 секунд благодаря кэшу.
SCHEDULER_INTERVAL = min(int(os.getenv("CHECK_INTERVAL_SECONDS", "30")), 60)
WEATHER_CACHE_MIN = int(os.getenv("WEATHER_CACHE_MIN", "10"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "180"))

PORT = int(os.getenv("PORT", "8080"))
LAT = float(os.getenv("LATITUDE", "46.56"))
LON = float(os.getenv("LONGITUDE", "30.86"))
LOCATION_NAME = os.getenv("LOCATION_NAME", "Фонтанка")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
weather = WeatherService(LAT, LON, TIMEZONE)

TARGET_CHAT_ID: int | None = None
if CHAT_ID_ENV:
    try:
        TARGET_CHAT_ID = int(CHAT_ID_ENV)
    except ValueError:
        log.error("CHAT_ID must be an integer")

# Кэш погоды: защищает Open-Meteo от лишних запросов.
LAST_WEATHER: FontankaData | None = None
LAST_WEATHER_AT: datetime | None = None

# Защита от повторных погодных предупреждений.
LAST_WEATHER_ALERT_SIGNATURE = ""
LAST_WEATHER_ALERT_AT: datetime | None = None


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌤 Погода", callback_data="weather"),
                InlineKeyboardButton(text="🌊 Море", callback_data="sea"),
            ],
            [
                InlineKeyboardButton(text="📅 7 дней", callback_data="forecast"),
                InlineKeyboardButton(text="🏖 Пляж", callback_data="beach"),
            ],
            [
                InlineKeyboardButton(text="💡 Факт дня", callback_data="fact"),
                InlineKeyboardButton(text="🎯 Совет", callback_data="tip"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Предупреждения", callback_data="alerts"),
                InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh"),
            ],
        ]
    )


def is_admin(user_id: int | None) -> bool:
    return bool(ADMIN_USER_ID and user_id == ADMIN_USER_ID)


def direction(deg: float | None) -> str:
    if deg is None:
        return "—"
    dirs = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    return dirs[int((deg + 22.5) // 45) % 8]


def safe_number(value, digits=1, suffix=""):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def weather_text(data: FontankaData) -> str:
    return (
        f"🌤 <b>{LOCATION_NAME} — погода</b>\n\n"
        f"🌡 Воздух: <b>{safe_number(data.air_temp, 1, '°C')}</b>\n"
        f"🥵 Ощущается: <b>{safe_number(data.feels_like, 1, '°C')}</b>\n"
        f"💨 Ветер: <b>{safe_number(data.wind_speed, 1, ' м/с')}</b> "
        f"{direction(data.wind_dir)}\n"
        f"💨 Порывы: <b>{safe_number(data.wind_gusts, 1, ' м/с')}</b>\n"
        f"💧 Влажность: <b>{data.humidity}%</b>\n"
        f"☔ Осадки: <b>{data.precip_prob}%</b>\n"
        f"{data.weather_emoji} {data.weather_desc}\n\n"
        f"🌅 Восход: {data.sunrise}\n"
        f"🌇 Закат: {data.sunset}"
    )


def sea_text(data: FontankaData) -> str:
    return (
        f"🌊 <b>{LOCATION_NAME} — море</b>\n\n"
        f"💧 Температура воды: <b>{safe_number(data.water_temp, 1, '°C')}</b>\n"
        f"🌊 Высота волн: <b>{safe_number(data.wave_height, 2, ' м')}</b>\n"
        f"🌀 Направление волн: <b>{direction(data.wave_dir)}</b>\n"
        f"🌬 Ветер: <b>{safe_number(data.wind_speed, 1, ' м/с')}</b>\n\n"
        f"{data.sea_rating}"
    )


def forecast_text(data: FontankaData) -> str:
    lines = [f"📅 <b>{LOCATION_NAME} — прогноз на 7 дней</b>", ""]
    for d in data.daily:
        lines.append(
            f"<b>{d['date']}</b> {d['emoji']} "
            f"<b>{d['tmax']:+.0f}° / {d['tmin']:+.0f}°</b> "
            f"☔ {d['rain']:.0f}% 💨 {d['wind']:.0f} м/с"
        )
    return "\n".join(lines)


def alerts_text(data: FontankaData) -> str:
    if not data.alerts:
        return (
            "✅ <b>Серьёзных погодных предупреждений сейчас нет.</b>\n\n"
            "Обычный режим отдыха."
        )
    return (
        "⚠️ <b>Погодные предупреждения</b>\n\n"
        + "\n\n".join(f"• {a}" for a in data.alerts)
    )


async def get_current(force: bool = False) -> FontankaData:
    """
    Получает текущую погоду.
    Повторные запросы в течение WEATHER_CACHE_MIN минут берутся из кэша.
    Если API временно недоступен, используется последняя успешная копия.
    """
    global LAST_WEATHER, LAST_WEATHER_AT

    now = datetime.now(TIMEZONE)
    if (
        not force
        and LAST_WEATHER is not None
        and LAST_WEATHER_AT is not None
        and now - LAST_WEATHER_AT < timedelta(minutes=WEATHER_CACHE_MIN)
    ):
        return LAST_WEATHER

    try:
        data = await weather.current()
        LAST_WEATHER = data
        LAST_WEATHER_AT = now
        return data
    except Exception:
        if LAST_WEATHER is not None:
            log.exception("Weather refresh failed; using cached data")
            return LAST_WEATHER
        raise


async def send_morning(chat_id: int) -> None:
    data = await get_current(force=True)
    text = (
        "☀️ <b>ДОБРОЕ УТРО, ФОНТАНКА!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{weather_text(data)}\n\n"
        f"🌊 {data.sea_rating}\n\n"
        f"🏖 <b>Совет:</b> {random.choice(BEACH_TIPS)}\n\n"
        f"💡 <b>Факт:</b> {random.choice(FACTS)}"
    )
    await bot.send_message(chat_id, text, reply_markup=main_keyboard())


async def send_afternoon(chat_id: int) -> None:
    data = await get_current(force=True)
    text = (
        "☀️ <b>ФОНТАНКА — ДНЕВНОЕ ОБНОВЛЕНИЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🌡 Воздух: <b>{safe_number(data.air_temp, 1, '°C')}</b>\n"
        f"🌊 Вода: <b>{safe_number(data.water_temp, 1, '°C')}</b>\n"
        f"〰️ Волны: <b>{safe_number(data.wave_height, 2, ' м')}</b>\n"
        f"💨 Ветер: <b>{safe_number(data.wind_speed, 1, ' м/с')}</b>\n"
        f"☔ Осадки: <b>{data.precip_prob}%</b>\n\n"
        f"🏖 <b>{data.beach_rating}</b>\n\n"
        f"💡 {random.choice(BEACH_TIPS)}"
    )
    await bot.send_message(chat_id, text, reply_markup=main_keyboard())


async def send_evening(chat_id: int) -> None:
    data = await get_current(force=True)
    text = (
        "🌅 <b>ВЕЧЕРНЯЯ ФОНТАНКА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{weather_text(data)}\n\n"
        f"🌊 {data.sea_rating}\n\n"
        f"💡 <b>Факт:</b> {random.choice(FACTS)}\n"
        f"🎯 <b>Совет:</b> {random.choice(BEACH_TIPS)}"
    )
    await bot.send_message(chat_id, text, reply_markup=main_keyboard())


async def send_photo(chat_id: int) -> None:
    try:
        photo = await wikimedia_photo()
        if not photo:
            await bot.send_message(
                chat_id,
                "📸 <b>Фото дня</b>\n\nПока не удалось получить фотографию.",
                reply_markup=main_keyboard(),
            )
            return

        caption = f"📸 <b>Фото дня</b>\n{photo['title']}"
        if photo.get("license"):
            caption += f"\nЛицензия: {photo['license']}"

        await bot.send_photo(
            chat_id,
            photo["url"],
            caption=caption,
            reply_markup=main_keyboard(),
        )
    except Exception:
        log.exception("Photo of the day failed")


async def weather_alert_loop() -> None:
    """
    Погодные предупреждения.
    Погода берётся из кэша, поэтому здесь нет постоянного обращения к Open-Meteo.
    """
    global LAST_WEATHER_ALERT_SIGNATURE, LAST_WEATHER_ALERT_AT

    while True:
        try:
            if TARGET_CHAT_ID:
                data = await get_current()
                if data.alerts:
                    now = datetime.now(TIMEZONE)
                    signature = "|".join(data.alerts)
                    cooldown_ok = (
                        LAST_WEATHER_ALERT_AT is None
                        or now - LAST_WEATHER_ALERT_AT
                        >= timedelta(minutes=ALERT_COOLDOWN_MIN)
                    )
                    if (
                        signature != LAST_WEATHER_ALERT_SIGNATURE
                        or cooldown_ok
                    ):
                        await bot.send_message(
                            TARGET_CHAT_ID,
                            "🚨 <b>ВАЖНОЕ ПОГОДНОЕ ПРЕДУПРЕЖДЕНИЕ</b>\n\n"
                            + "\n\n".join(
                                f"• {alert}" for alert in data.alerts
                            ),
                            reply_markup=main_keyboard(),
                        )
                        LAST_WEATHER_ALERT_SIGNATURE = signature
                        LAST_WEATHER_ALERT_AT = now
        except Exception:
            log.exception("Weather alert check failed")
        await asyncio.sleep(SCHEDULER_INTERVAL)


async def automatic_posts_loop() -> None:
    """
    Автоматические публикации:
    09:00 — утро
    14:00 — дневное обновление
    19:00 — вечер
    Окно 10 минут позволяет пережить небольшой перезапуск Railway.
    """
    sent: set[tuple[str, str]] = set()

    while True:
        try:
            now = datetime.now(TIMEZONE)
            if TARGET_CHAT_ID:
                schedules = (
                    ("morning", MORNING_HOUR, send_morning),
                    ("afternoon", AFTERNOON_HOUR, send_afternoon),
                    ("evening", EVENING_HOUR, send_evening),
                )
                for name, hour, function in schedules:
                    key = (now.date().isoformat(), name)
                    if (
                        now.hour == hour
                        and now.minute < 10
                        and key not in sent
                    ):
                        try:
                            await function(TARGET_CHAT_ID)
                            sent.add(key)
                            log.info(
                                "Automatic %s post sent at %s",
                                name,
                                now.isoformat(),
                            )
                        except Exception:
                            log.exception(
                                "Automatic %s post failed", name
                            )

                sent = {
                    item
                    for item in sent
                    if item[0] == now.date().isoformat()
                }
        except Exception:
            log.exception("Automatic scheduler error")
        await asyncio.sleep(SCHEDULER_INTERVAL)


@dp.message(CommandStart())
async def start_cmd(message: Message) -> None:
    await message.answer(
        f"🏖 <b>ФОНТАНКА BEACH</b>\n\n"
        f"Погода, море, волны, прогноз, пляж, факты "
        f"и предупреждения для {LOCATION_NAME}.\n\n"
        f"☀️ Я сам публикую сводки в группе утром, днём и вечером.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("id"))
async def id_cmd(message: Message) -> None:
    await message.answer(
        f"🆔 Chat ID: <code>{message.chat.id}</code>"
    )


@dp.message(Command("test"))
async def test_cmd(message: Message) -> None:
    if not is_admin(
        message.from_user.id if message.from_user else None
    ):
        return
    await send_morning(message.chat.id)


@dp.message(Command("testday"))
async def testday_cmd(message: Message) -> None:
    if not is_admin(
        message.from_user.id if message.from_user else None
    ):
        return
    await send_afternoon(message.chat.id)


@dp.message(Command("testevening"))
async def testevening_cmd(message: Message) -> None:
    if not is_admin(
        message.from_user.id if message.from_user else None
    ):
        return
    await send_evening(message.chat.id)


@dp.message(Command("testphoto"))
async def testphoto_cmd(message: Message) -> None:
    if not is_admin(
        message.from_user.id if message.from_user else None
    ):
        return
    await send_photo(message.chat.id)


@dp.callback_query(
    F.data.in_(
        {
            "weather",
            "sea",
            "forecast",
            "beach",
            "fact",
            "tip",
            "alerts",
            "refresh",
        }
    )
)
async def callbacks(query: CallbackQuery) -> None:
    await query.answer()
    try:
        data = await get_current()

        if query.data in ("weather", "refresh"):
            text = weather_text(data)
        elif query.data == "sea":
            text = sea_text(data)
        elif query.data == "forecast":
            forecast = await weather.forecast7()
            text = forecast_text(forecast)
        elif query.data == "beach":
            text = (
                f"🏖 <b>ПЛЯЖ СЕГОДНЯ</b>\n\n"
                f"{data.beach_rating}\n\n"
                f"🎯 {random.choice(BEACH_TIPS)}"
            )
        elif query.data == "fact":
            text = (
                f"💡 <b>ФАКТ ДНЯ</b>\n\n"
                f"{random.choice(FACTS)}"
            )
        elif query.data == "tip":
            text = (
                f"🎯 <b>СОВЕТ ОТДЫХАЮЩИМ</b>\n\n"
                f"{random.choice(BEACH_TIPS)}"
            )
        else:
            text = alerts_text(data)

        if query.message:
            try:
                await query.message.edit_text(
                    text,
                    reply_markup=main_keyboard(),
                )
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    raise
    except TelegramForbiddenError:
        log.warning(
            "Telegram forbids bot from writing to this chat"
        )
    except Exception:
        log.exception("Callback error")


async def health(_: web.Request) -> web.Response:
    return web.Response(text="Fontanka bot is alive")


async def start_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )
    await site.start()
    return runner


async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)

    runner = await start_health_server()

    # Два независимых фоновых процесса:
    # 1) автоматические посты
    # 2) погодные предупреждения
    asyncio.create_task(automatic_posts_loop())
    asyncio.create_task(weather_alert_loop())

    me = await bot.get_me()
    log.info("Bot started: @%s", me.username)
    log.info(
        "Automatic posts: %02d:00 / %02d:00 / %02d:00 (%s)",
        MORNING_HOUR,
        AFTERNOON_HOUR,
        EVENING_HOUR,
        TIMEZONE,
    )
    if TARGET_CHAT_ID is None:
        log.warning(
            "CHAT_ID is not set. Automatic posts will not be sent "
            "to a fixed group."
        )
    else:
        log.info("Automatic posts target chat: %s", TARGET_CHAT_ID)

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
