# Kadroff Info Bot

Telegram-бот для кадрового агентства, подключён к Google Sheets.

## 🔧 Как запустить

### Локально

1. Установи зависимости:
```
pip install -r requirements.txt
```

2. Положи файл `credentials.json` в корень рядом с `job_bot.py`.

3. Экспортируй токен:
```
export BOT_TOKEN=your_bot_token
```

4. Запусти бота:
```
python job_bot.py
```

### На Railway

1. Загрузи проект на GitHub
2. Подключи к Railway
3. Добавь переменные:
   - `BOT_TOKEN`
4. Загрузи файл `credentials.json` через Settings > Files

## 📌 Возможности

- Команда `/vacancies` показывает открытые вакансии
- Команда `/faq` — ответы на частые вопросы
- Команда `/apply` — подать заявку
