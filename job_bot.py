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

SPREADSHEET_ID = "10-sXX7zmsjxcLBGoua876P9eopBwPSe4f6P0NfmRDfY"

def get_vacancies():
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Вакансии")
    records = sheet.get_all_records()
    return [row for row in records if row.get('СТАТУС', '').strip().upper() == 'ОТКРЫТА']

def get_faq():
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Вопросы")
    return sheet.get_all_records()

def save_application_to_sheet(name, phone, vacancy, username):
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Отклики")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, name, phone, vacancy, f"@{username}" if username else "без username"], value_input_option="USER_ENTERED")

# ===== States =====
STATE_WAITING_FOR_FIO = 1
STATE_WAITING_FOR_PHONE = 2

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📋 Актуальные вакансии", callback_data="find_jobs")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Здравствуйте! Я бот кадрового агентства.\n\n"
        "Напишите название профессии или выберите кнопку ниже, чтобы посмотреть открытые вакансии.",
        reply_markup=markup
    )

async def jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_vacancies()
    if not data:
        text = "Нет открытых вакансий на данный момент."
    else:
        text = "\n".join([f"• {row['Вакансия']}" for row in data])
    if update.message:
        await update.message.reply_text("Список актуальных вакансий:\n\n" + text)
    elif update.callback_query:
        await update.callback_query.message.reply_text("Список актуальных вакансий:\n\n" + text)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "find_jobs":
        await jobs(update, context)
        await query.message.reply_text("Какая вакансия вас интересует? Напишите её название.")
    elif query.data == "back":
        await back(update, context)
    elif query.data.startswith("apply_"):
        await handle_apply(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    faq = get_faq()
    for row in faq:
        if text in row['Вопрос'].lower():
            await update.message.reply_text(row['Ответ'])
            return

    data = get_vacancies()
    matches = []
    for row in data:
        if text in row['Вакансия'].lower() or difflib.get_close_matches(text, [row['Вакансия'].lower()], cutoff=0.6):
            matches.append(row)

    if matches:
        context.user_data['vacancy_matches'] = matches
        for i, row in enumerate(matches):
            description_text = f"\n📃 {row['Описание']}" if row.get("Описание") else ""
            response = (
                f"📌 *{row['Вакансия']}*\n\n"
                f"💰 Часовая ставка: {row['Часовая ставка']}\n"
                f"🕐 Вахта 12 ч (30/30): {row['Вахта по 12 часов (30/30)']}\n"
                f"🕑 Вахта 11 ч (60/30): {row['Вахта по 11 ч (60/30)']}\n"
                f"{description_text}"
            )
            keyboard = [
                [InlineKeyboardButton("Откликнуться", callback_data=f"apply_{i}")],
                [InlineKeyboardButton("Назад", callback_data="back")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_markdown(response, reply_markup=markup)
    else:
        await update.message.reply_text("Не нашёл вакансию по вашему запросу. Попробуйте написать её полнее.")

async def handle_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    index = int(query.data.split("_")[1])
    data = context.user_data.get('vacancy_matches', [])
    if index >= len(data):
        await query.answer("Ошибка: вакансия не найдена.")
        return
    vacancy = data[index]['Вакансия']
    context.user_data['vacancy'] = vacancy
    context.user_data['state'] = STATE_WAITING_FOR_FIO
    await query.message.edit_text(f"Вы выбрали вакансию: *{vacancy}*\n\nПожалуйста, введите ваше ФИО:")

async def handle_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fio = update.message.text.strip()
    if not re.match(r"^[А-Яа-яЁё\s\-]+$", fio):
        await update.message.reply_text("Неверный формат ФИО. Введите снова.")
        return
    context.user_data['fio'] = fio
    context.user_data['state'] = STATE_WAITING_FOR_PHONE
    await update.message.reply_text("Теперь введите ваш номер телефона:")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.match(r"^[\d+\-\(\)\s]+$", phone):
        await update.message.reply_text("Неверный номер телефона. Попробуйте снова.")
        return
    context.user_data['phone'] = phone
    save_application_to_sheet(
        name=context.user_data['fio'],
        phone=phone,
        vacancy=context.user_data['vacancy'],
        username=update.message.from_user.username
    )
    await update.message.reply_text("Спасибо! Ваш отклик сохранён.")
    context.user_data.clear()

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Напишите название профессии или нажмите кнопку ниже.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Актуальные вакансии", callback_data="find_jobs")]])
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    if state == STATE_WAITING_FOR_FIO:
        await handle_fio(update, context)
    elif state == STATE_WAITING_FOR_PHONE:
        await handle_phone(update, context)
    else:
        await handle_message(update, context)

# ===== Bot setup =====
def run_bot():
    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jobs", jobs))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.run_polling()

# ===== Main start =====
if __name__ == '__main__':
    Thread(target=run_flask).start()
    run_bot()
