from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import difflib
import re
from datetime import datetime
import asyncio

# ===== Flask keep-alive server =====
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "I'm alive!"

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080)

# ===== Google Sheets setup =====
scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Открываем таблицу по ключу (замени на свой ключ)
SPREADSHEET_KEY = "10-sXX7zmsjxcLBGoua876P9eopBwPSe4f6P0NfmRDfY"

def get_vacancies():
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet("Вакансии")
    records = sheet.get_all_records()
    # фильтруем только открытые вакансии (СТАТУС == "ОТКРЫТА")
    open_jobs = [row for row in records if row.get("СТАТУС", "").strip().upper() == "ОТКРЫТА"]
    return open_jobs

def get_questions():
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet("Вопросы")
    return sheet.get_all_records()

def save_application_to_sheet(name, phone, vacancy, username):
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet("Отклики")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, name, phone, vacancy, f"@{username}" if username else "без username"], value_input_option="USER_ENTERED")

# ===== States =====
STATE_WAITING_FOR_FIO = 1
STATE_WAITING_FOR_PHONE = 2

# ===== Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("АКТУАЛЬНЫЕ ВАКАНСИИ", callback_data="find_jobs")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Здравствуйте! Я бот кадрового агентства.\n\n"
        "Я помогу вам подобрать вакансию. Напишите название профессии или нажмите кнопку ниже.",
        reply_markup=markup
    )

async def list_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_jobs = get_vacancies()
    if not open_jobs:
        msg = "Сейчас нет открытых вакансий."
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg)
        return

    for i, row in enumerate(open_jobs):
        description = row.get('Описание', '').strip()
        description_text = f"\n\n📃 Описание вакансии:\n{description}" if description else ""
        text = (
            f"📌 *{row['Вакансия']}*\n\n"
            f"💵 Часовая ставка: {row.get('Часовая ставка', 'не указана')}\n"
            f"🕐 Вахта по 12 часов (30/30): {row.get('Вахта по 12 часов (30/30)', 'нет данных')}\n"
            f"🕑 Вахта по 11 часов (60/30): {row.get('Вахта по 11 ч (60/30)', 'нет данных')}\n"
            f"📌 Статус: {row.get('СТАТУС', 'не указан')}"
            f"{description_text}"
        )
        keyboard = [
            [InlineKeyboardButton("Откликнуться", callback_data=f"apply_{i}")],
            [InlineKeyboardButton("Назад", callback_data="back")]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_markdown(text, reply_markup=markup)
        elif update.callback_query:
            await update.callback_query.message.reply_markdown(text, reply_markup=markup)
    if update.callback_query:
        await update.callback_query.answer()

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "find_jobs":
        await list_vacancies(update, context)
    elif query.data == "back":
        await start(update, context)
    elif query.data.startswith("apply_"):
        await start_application(update, context)

async def start_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    index = int(query.data.split("_")[1])
    open_jobs = get_vacancies()
    if index < 0 or index >= len(open_jobs):
        await query.answer("Вакансия не найдена.")
        return
    vacancy = open_jobs[index]['Вакансия']
    context.user_data['vacancy'] = vacancy
    context.user_data['state'] = STATE_WAITING_FOR_FIO
    await query.message.edit_text(f"Вы выбрали вакансию:\n\n*{vacancy}*\n\nПожалуйста, введите ваше ФИО:", parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    if state == STATE_WAITING_FOR_FIO:
        await handle_fio(update, context)
    elif state == STATE_WAITING_FOR_PHONE:
        await handle_phone(update, context)
    else:
        # При вводе текста без активного состояния - можно попытаться искать вакансии по ключевым словам
        await search_vacancy(update, context)

async def handle_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fio = update.message.text.strip()
    if not re.match(r"^[А-Яа-яЁё\s\-]+$", fio):
        await update.message.reply_text("Пожалуйста, введите корректное ФИО (только русские буквы, пробелы и дефисы).")
        return
    context.user_data['fio'] = fio
    context.user_data['state'] = STATE_WAITING_FOR_PHONE
    await update.message.reply_text("Спасибо! Теперь введите, пожалуйста, ваш номер телефона:")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.match(r"^[\d+\-\(\)\s]+$", phone):
        await update.message.reply_text("Неверный формат номера телефона. Введите заново.")
        return
    context.user_data['phone'] = phone
    username = update.message.from_user.username if update.message.from_user else None
    save_application_to_sheet(
        context.user_data['fio'],
        context.user_data['phone'],
        context.user_data['vacancy'],
        username
    )
    await update.message.reply_text(
        f"Ваш отклик на вакансию *{context.user_data['vacancy']}* принят!\n\n"
        f"ФИО: {context.user_data['fio']}\n"
        f"Телефон: {context.user_data['phone']}\n\nСпасибо за отклик!",
        parse_mode='Markdown'
    )
    context.user_data.clear()

async def search_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    open_jobs = get_vacancies()
    matches = []
    for row in open_jobs:
        vacancy_lines = row['Вакансия'].lower().splitlines()
        for line in vacancy_lines:
            if text in line or difflib.get_close_matches(text, [line], cutoff=0.6):
                matches.append(row)
                break

    if matches:
        for i, row in enumerate(matches):
            description = row.get('Описание', '').strip()
            description_text = f"\n\n📃 Описание вакансии:\n{description}" if description else ""
            text_response = (
                f"📌 *{row['Вакансия']}*\n\n"
                f"💵 Часовая ставка: {row.get('Часовая ставка', 'не указана')}\n"
                f"🕐 Вахта по 12 часов (30/30): {row.get('Вахта по 12 часов (30/30)', 'нет данных')}\n"
                f"🕑 Вахта по 11 часов (60/30): {row.get('Вахта по 11 ч (60/30)', 'нет данных')}\n"
                f"📌 Статус: {row.get('СТАТУС', 'не указан')}"
                f"{description_text}"
            )
            keyboard = [
                [InlineKeyboardButton("Откликнуться", callback_data=f"apply_{i}")],
                [InlineKeyboardButton("Назад", callback_data="back")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_markdown(text_response, reply_markup=markup)
    else:
        await update.message.reply_text("По вашему запросу вакансий не найдено. Попробуйте написать название вакансии или нажмите кнопку 'АКТУАЛЬНЫЕ ВАКАНСИИ'.")

# ===== Bot setup =====
def run_bot():
    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jobs", list_vacancies))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

# ===== Main =====
if __name__ == '__main__':
    Thread(target=run_flask).start()
    run_bot()
