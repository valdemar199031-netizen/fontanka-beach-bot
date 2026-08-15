import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from content import FACTS, BEACH_TIPS
from services import FontankaData, WeatherService
from photos import wikimedia_photo

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("fontanka")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
CHAT_ID_ENV = os.getenv("CHAT_ID", "")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Kyiv"))
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "9"))
AFTERNOON_HOUR = int(os.getenv("AFTERNOON_HOUR", "13"))
EVENING_HOUR = int(os.getenv("EVENING_HOUR", "18"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "180"))
PORT = int(os.getenv("PORT", "8080"))
LAT = float(os.getenv("LATITUDE", "46.56"))
LON = float(os.getenv("LONGITUDE", "30.86"))
LOCATION_NAME = os.getenv("LOCATION_NAME", "Фонтанка")


def parse_chat_id() -> int | None:
    if CHAT_ID_ENV.strip():
        try:
            return int(CHAT_ID_ENV.strip())
        except ValueError:
            log.error("CHAT_ID must be an integer")
    return None

TARGET_CHAT_ID = parse_chat_id()
LAST_ALERT_SIGNATURE = ""
LAST_ALERT_AT: datetime | None = None

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
weather = WeatherService(LAT, LON, TIMEZONE)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌤 Погода", callback_data="weather"), InlineKeyboardButton(text="🌊 Море", callback_data="sea")],
        [InlineKeyboardButton(text="📅 7 дней", callback_data="forecast"), InlineKeyboardButton(text="🏖 Пляж", callback_data="beach")],
        [InlineKeyboardButton(text="💡 Факт дня", callback_data="fact"), InlineKeyboardButton(text="🎯 Совет", callback_data="tip")],
        [InlineKeyboardButton(text="⚠️ Предупреждения", callback_data="alerts"), InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")],
    ])


def is_admin(user_id: int | None) -> bool:
    return bool(ADMIN_USER_ID and user_id == ADMIN_USER_ID)


def target_chat(message: Message) -> int:
    return TARGET_CHAT_ID or message.chat.id


def direction(deg: float | None) -> str:
    if deg is None:
        return "—"
    dirs = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    return dirs[int((deg + 22.5) // 45) % 8]


def weather_text(data: FontankaData) -> str:
    return (
        f"🌤 <b>{LOCATION_NAME} — погода</b>\n\n"
        f"🌡 Воздух: <b>{data.air_temp:+.1f}°C</b>\n"
        f"🥵 Ощущается: <b>{data.feels_like:+.1f}°C</b>\n"
        f"💨 Ветер: <b>{data.wind_speed:.1f} м/с</b> {direction(data.wind_dir)}\n"
        f"💨 Порывы: <b>{data.wind_gusts:.1f} м/с</b>\n"
        f"💧 Влажность: <b>{data.humidity}%</b>\n"
        f"☔ Осадки: <b>{data.precip_prob}%</b>\n"
        f"{data.weather_emoji} {data.weather_desc}\n\n"
        f"🌅 Восход: {data.sunrise}\n"
        f"🌇 Закат: {data.sunset}"
    )


def sea_text(data: FontankaData) -> str:
    wave = f"{data.wave_height:.2f} м" if data.wave_height is not None else "—"
    water = f"{data.water_temp:.1f}°C" if data.water_temp is not None else "—"
    return (
        f"🌊 <b>{LOCATION_NAME} — море</b>\n\n"
        f"💧 Температура воды: <b>{water}</b>\n"
        f"🌊 Высота волн: <b>{wave}</b>\n"
        f"🌀 Направление волн: <b>{direction(data.wave_dir)}</b>\n"
        f"🌬 Ветер: <b>{data.wind_speed:.1f} м/с</b>\n\n"
        f"{data.sea_rating}"
    )


def forecast_text(data: FontankaData) -> str:
    lines = [f"📅 <b>{LOCATION_NAME} — прогноз на 7 дней</b>", ""]
    for d in data.daily:
        lines.append(
            f"<b>{d['date']}</b> {d['emoji']}  <b>{d['tmax']:+.0f}° / {d['tmin']:+.0f}°</b>  "
            f"☔ {d['rain']:.0f}%  💨 {d['wind']:.0f} м/с"
        )
    return "\n".join(lines)


def alerts_text(data: FontankaData) -> str:
    alerts = data.alerts
    if not alerts:
        return "✅ <b>Серьёзных погодных предупреждений сейчас нет.</b>\n\nОбычный режим отдыха."
    return "⚠️ <b>Предупреждения</b>\n\n" + "\n\n".join(f"• {a}" for a in alerts)


async def send_main(chat_id: int, text: str) -> None:
    await bot.send_message(chat_id, text, reply_markup=main_keyboard())


async def send_morning(chat_id: int) -> None:
    data = await weather.current()
    text = (
        f"☀️ <b>Доброе утро, Фонтанка!</b>\n\n"
        + weather_text(data)
        + "\n\n🏖 <b>Пляжный совет:</b> " + random.choice(BEACH_TIPS)
    )
    await send_main(chat_id, text)


async def send_evening(chat_id: int) -> None:
    data = await weather.current()
    text = (
        f"🌅 <b>Вечерняя сводка — {LOCATION_NAME}</b>\n\n"
        + weather_text(data)
        + "\n\n🌊 " + data.sea_rating
    )
    await send_main(chat_id, text)


async def send_fact(chat_id: int) -> None:
    await bot.send_message(chat_id, f"💡 <b>Факт дня</b>\n\n{random.choice(FACTS)}", reply_markup=main_keyboard())


async def send_photo(chat_id: int) -> None:
    photo = await wikimedia_photo()
    if not photo:
        return
    caption = f"📸 <b>Фото дня</b>\n{photo['title']}"
    if photo.get("license"):
        caption += f"\nЛицензия: {photo['license']}"
    await bot.send_photo(chat_id, photo["url"], caption=caption, reply_markup=main_keyboard())


async def scheduler_loop() -> None:
    global LAST_ALERT_SIGNATURE, LAST_ALERT_AT
    sent_dates: set[tuple[str, str]] = set()
    while True:
        try:
            now = datetime.now(TIMEZONE)
            chat_id = TARGET_CHAT_ID
            if chat_id:
                for name, hour in (("morning", MORNING_HOUR), ("afternoon", AFTERNOON_HOUR), ("evening", EVENING_HOUR)):
                    key = (now.date().isoformat(), name)
                    if now.hour == hour and now.minute < 2 and key not in sent_dates:
                        if name == "morning":
                            await send_morning(chat_id)
                        elif name == "afternoon":
                            await send_fact(chat_id)
                            await send_photo(chat_id)
                        else:
                            await send_evening(chat_id)
                        sent_dates.add(key)

                data = await weather.current()
                if data.alerts:
                    signature = "|".join(data.alerts)
                    cooldown_ok = LAST_ALERT_AT is None or (now - LAST_ALERT_AT) >= timedelta(minutes=ALERT_COOLDOWN_MIN)
                    if signature != LAST_ALERT_SIGNATURE or cooldown_ok:
                        await bot.send_message(chat_id, "🚨 <b>Важное погодное предупреждение</b>\n\n" + "\n\n".join(f"• {a}" for a in data.alerts), reply_markup=main_keyboard())
                        LAST_ALERT_SIGNATURE = signature
                        LAST_ALERT_AT = now
                # prevent memory growth
                sent_dates = {k for k in sent_dates if k[0] == now.date().isoformat()}
        except Exception:
            log.exception("Scheduler error")
        await asyncio.sleep(CHECK_INTERVAL)


@dp.message(CommandStart())
async def start_cmd(message: Message) -> None:
    await message.answer(
        f"🌊 <b>Фонтанка — бот отдыха</b>\n\n"
        f"Погода, море, волны, прогноз, пляжные советы и предупреждения для {LOCATION_NAME}.\n\n"
        f"Нажми кнопку ниже 👇",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("setchat"))
async def setchat_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Эта команда доступна только администратору, указанному в ADMIN_USER_ID.")
        return
    await message.answer(
        "✅ ID этого чата: <code>" + str(message.chat.id) + "</code>\n\n"
        "Добавь его в .env как CHAT_ID=... и перезапусти сервис."
    )


@dp.message(Command("id"))
async def id_cmd(message: Message) -> None:
    await message.answer(f"🆔 Chat ID: <code>{message.chat.id}</code>")


@dp.message(Command("test"))
async def test_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await send_morning(message.chat.id)


@dp.callback_query(F.data.in_({"weather", "sea", "forecast", "beach", "fact", "tip", "alerts", "refresh"}))
async def callbacks(query: CallbackQuery) -> None:
    await query.answer()
    data = await weather.current()
    if query.data in ("weather", "refresh"):
        text = weather_text(data)
    elif query.data == "sea":
        text = sea_text(data)
    elif query.data == "forecast":
        text = forecast_text(await weather.forecast7())
    elif query.data == "beach":
        text = f"🏖 <b>Пляж сегодня</b>\n\n{data.beach_rating}\n\n🎯 {random.choice(BEACH_TIPS)}"
    elif query.data == "fact":
        text = f"💡 <b>Факт дня</b>\n\n{random.choice(FACTS)}"
    elif query.data == "tip":
        text = f"🎯 <b>Совет отдыхающим</b>\n\n{random.choice(BEACH_TIPS)}"
    else:
        text = alerts_text(data)

    if query.message:
        await query.message.edit_text(text, reply_markup=main_keyboard())


async def health(_: web.Request) -> web.Response:
    return web.Response(text="Fontanka bot is alive")


async def start_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    return runner


async def main() -> None:
    global TARGET_CHAT_ID
    await bot.delete_webhook(drop_pending_updates=True)
    runner = await start_health_server()
    asyncio.create_task(scheduler_loop())
    me = await bot.get_me()
    log.info("Bot started: @%s", me.username)
    if TARGET_CHAT_ID is None:
        log.warning("CHAT_ID is not set. Put the bot in the group and use /id or /setchat.")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
