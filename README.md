# 🌊 Fontanka Telegram Bot — Railway

Готовый Telegram-бот для группы отдыхающих в Фонтанке.

## Возможности

- 🌤 текущая погода
- 🌊 температура воды
- 🌊 высота и направление волн
- 💨 ветер и порывы
- ☔ вероятность осадков
- 🌅 восход/закат
- 📅 прогноз на 7 дней
- 🏖 оценка пляжных условий
- ⚠️ автоматические погодные предупреждения
- 💡 факты
- 🎯 советы отдыхающим
- 📸 фото дня
- 🔘 интерактивные inline-кнопки
- 🕘 автоматические публикации утром, днём и вечером
- 🔁 автоматический restart при падении через Railway
- `/id`, `/setchat`, `/test` для настройки

## Запуск на Railway

1. Загрузи содержимое этой папки в GitHub-репозиторий.
2. В Railway: **New Project → Deploy from GitHub Repo** → выбери репозиторий.
3. Railway увидит `railway.json` и запустит `python bot.py`.
4. В **Variables** добавь переменные:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_USER_ID=твой_Telegram_ID
CHAT_ID=-100xxxxxxxxxx
LATITUDE=46.56
LONGITUDE=30.86
LOCATION_NAME=Фонтанка
TIMEZONE=Europe/Kyiv
MORNING_HOUR=9
AFTERNOON_HOUR=13
EVENING_HOUR=18
CHECK_INTERVAL_SECONDS=60
ALERT_COOLDOWN_MIN=180
```

`PORT` Railway подставит сам. Боту всё равно поднимет HTTP health endpoint на `0.0.0.0:$PORT`.

## Как получить CHAT_ID

Добавь бота в группу и выполни:

```text
/id
```

Бот покажет ID группы.

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Важно

Не загружай `.env` и Telegram token в GitHub. Используй Railway Variables.

## Источники

Погода и морские данные: Open-Meteo Weather API и Open-Meteo Marine API.
