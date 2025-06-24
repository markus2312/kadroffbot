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

def get_data():
    sheet = client.open("Передовик вакансии БОТ").sheet1
    return sheet.get_all_records()

def save_application_to_sheet(name, phone, vacancy, username):
    sheet = client.open_by_key("10TcAZPunK079FBN1gNQIU4XmInMEQ8Qz4CWeA6oDGvI")
    worksheet = sheet.worksheet("bot otkliki")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worksheet.append_row([now, name, phone, vacancy, f"@{username}" if username else "без username"], value_input_option="USER_ENTERED")

# ===== States =====
STATE_WAITING_FOR_FIO = 1
STATE_WAITING_FOR_PHONE = 2

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("АКТУАЛЬНЫЕ ВАКАНСИИ", callback_data="find_jobs")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Я помогу вам подобрать вакансию. Напишите название профессии или посмотрите список открытых вакансий", reply_markup=markup)

async def jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_data()
    lines = []
    for row in data:
        if row.get('СТАТУС', '').strip().upper() == 'НАБИРАЕМ':
            for line in row['Вакансия'].splitlines():
                lines.append(f"• {line.strip()}")
    text = "\n".join(lines)

    if update.message:
        await update.message.reply_text("Список актуальных вакансий:\n\n" + text)
        await asyncio.sleep(1)
        await update.message.reply_text("Какая вакансия интересует?")
    elif update.callback_query:
        await update.callback_query.message.reply_text("Список актуальных вакансий:\n\n" + text)
        await asyncio.sleep(1)
        await update.callback_query.message.reply_text("Какая вакансия интересует?")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "find_jobs":
        await jobs(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    data = get_data()
    matches = []

    for row in data:
        for line in row['Вакансия'].splitlines():
            if text in line.lower() or difflib.get_close_matches(text, [line.lower()], cutoff=0.6):
                matches.append(row)
                break

    if matches:
        context.user_data['vacancy_matches'] = matches
        for i, row in enumerate(matches):
            description = row.get('Описание', '').strip()
            description_text = f"\n\n📃 Описание вакансии:\n\n{description}" if description else ""

            response = f"""
🔧 *{row['Вакансия']}*

📈 Часовая ставка:
{row['Часовая ставка']}

🕐 Вахта 30/30 по 12ч:
{row['Вахта по 12 часов (30/30)']}

🕑 Вахта 60/30 по 11ч:
{row['Вахта по 11 ч (60/30)']}

📌 Статус: {row.get('СТАТУС', 'не указан')}{description_text}
"""
            keyboard = [
                [InlineKeyboardButton("ОТКЛИКНУТЬСЯ", callback_data=f"apply_{i}"),
                 InlineKeyboardButton("НАЗАД", callback_data="back")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_markdown(response, reply_markup=markup)
    else:
        await update.message.reply_text("Не нашёл вакансию по вашему запросу. Попробуйте написать её полнее.")

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keyboard = [[InlineKeyboardButton("АКТУАЛЬНЫЕ ВАКАНСИИ", callback_data="find_jobs")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text(
        "Я помогу вам подобрать вакансию. Напишите название профессии или посмотрите список открытых вакансий",
        reply_markup=markup
    )

async def handle_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    index = int(query.data.split("_", 1)[1])
    data = context.user_data.get('vacancy_matches')

    if not data or index >= len(data):
        await query.answer("Не удалось найти вакансию.")
        return

    row = data[index]
    vacancy = row['Вакансия']
    context.user_data['vacancy'] = vacancy

    await query.answer()
    await query.message.edit_text(f"Вы откликнулись на вакансию: {vacancy}\n\nПожалуйста, введите ваше ФИО:")
    context.user_data['state'] = STATE_WAITING_FOR_FIO

async def handle_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fio = update.message.text.strip()
    if not re.match(r"^[А-Яа-яЁё\s-]+$", fio):
        await update.message.reply_text("Неверное ФИО. Введите снова.")
        return
    context.user_data['fio'] = fio
    context.user_data['state'] = STATE_WAITING_FOR_PHONE
    await update.message.reply_text("Теперь, пожалуйста, введите ваш номер телефона:")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.match(r"^[\d+\(\)\- ]+$", phone):
        await update.message.reply_text("Неверный номер. Попробуйте снова.")
        return

    context.user_data['phone'] = phone
    username = update.message.from_user.username
    save_application_to_sheet(
        context.user_data['fio'],
        context.user_data['phone'],
        context.user_data['vacancy'],
        username
    )
    await update.message.reply_text(f"Ваш отклик на вакансию {context.user_data['vacancy']} принят!\n"
                                    f"ФИО: {context.user_data['fio']}\n"
                                    f"Телефон: {context.user_data['phone']}\n\n"
                                    "Спасибо за отклик!")
    context.user_data['state'] = None

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
    app.add_handler(CallbackQueryHandler(handle_callback, pattern="find_jobs"))
    app.add_handler(CallbackQueryHandler(handle_apply, pattern=r"apply_\d+"))
    app.add_handler(CallbackQueryHandler(back, pattern="back"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.run_polling()

# ===== Main start =====
if __name__ == '__main__':
    Thread(target=run_flask).start()
    run_bot()
