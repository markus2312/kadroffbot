import os
import json
import re
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Google Sheets setup ---
scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

SPREADSHEET_KEY = "10-sXX7zmsjxcLBGoua876P9eopBwPSe4f6P0NfmRDfY"
VACANCIES_SHEET = "Вакансии"
APPLICATIONS_SHEET = "Отклики"

def get_vacancies():
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(VACANCIES_SHEET)
    return sheet.get_all_records()

def save_application(fio, phone, vacancy, username):
    sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(APPLICATIONS_SHEET)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, fio, phone, vacancy, f"@{username}" if username else "без username"], value_input_option="USER_ENTERED")

# --- Bot handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("АКТУАЛЬНЫЕ ВАКАНСИИ", callback_data="find_jobs")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Я помогу подобрать вакансию.\n"
        "Нажмите кнопку ниже, чтобы увидеть список открытых вакансий.",
        reply_markup=markup
    )

async def jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_vacancies()
    vacancies = [row for row in data if row.get('Статус', '').upper() in ('ОТКРЫТА', 'НАБИРАЕМ')]

    if not vacancies:
        text = "К сожалению, вакансии сейчас отсутствуют."
        if update.callback_query:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    for i, row in enumerate(vacancies):
        vacancy_name = row.get('Вакансия', 'Без названия')
        hourly_rate = row.get('Часовая ставка', 'Нет данных')
        description = row.get('Описание', '').strip()
        status = row.get('Статус', 'не указан')

        message_text = f"🔹 *{vacancy_name}*\n\n" \
                       f"💰 *Часовая ставка:*\n{hourly_rate}\n\n" \
                       f"📄 *Описание:*\n{description}\n\n" \
                       f"📌 *Статус:* {status}"

        keyboard = [
            [InlineKeyboardButton("Откликнуться", callback_data=f"apply_{i}")],
            [InlineKeyboardButton("Назад", callback_data="back")]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.message.reply_markdown(message_text, reply_markup=markup)
        else:
            await update.message.reply_markdown(message_text, reply_markup=markup)
        await asyncio.sleep(0.5)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "find_jobs":
        await jobs(update, context)
    elif query.data == "back":
        await start(update, context)
    elif query.data.startswith("apply_"):
        index = int(query.data.split("_")[1])
        data = get_vacancies()
        vacancies = [row for row in data if row.get('Статус', '').upper() in ('ОТКРЫТА', 'НАБИРАЕМ')]

        if 0 <= index < len(vacancies):
            vacancy = vacancies[index]['Вакансия']
            await query.message.reply_text(f"Вы выбрали вакансию:\n\n{vacancy}\n\nПожалуйста, отправьте ваше ФИО.")
            context.user_data['vacancy'] = vacancy
            context.user_data['state'] = 'waiting_for_fio'
        else:
            await query.message.reply_text("Ошибка: вакансия не найдена.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')

    if state == 'waiting_for_fio':
        fio = update.message.text.strip()
        if not re.match(r"^[А-Яа-яЁё\s-]+$", fio):
            await update.message.reply_text("Неверное ФИО. Пожалуйста, введите только русские буквы, пробелы и дефисы.")
            return
        context.user_data['fio'] = fio
        context.user_data['state'] = 'waiting_for_phone'
        await update.message.reply_text("Спасибо! Теперь введите, пожалуйста, номер телефона.")

    elif state == 'waiting_for_phone':
        phone = update.message.text.strip()
        if not re.match(r"^[\d+\(\)\-\s]+$", phone):
            await update.message.reply_text("Неверный номер телефона. Попробуйте снова.")
            return
        vacancy = context.user_data.get('vacancy')
        fio = context.user_data.get('fio')
        username = update.message.from_user.username or ""

        save_application(fio, phone, vacancy, username)

        await update.message.reply_text(
            f"Спасибо за отклик!\n\n"
            f"Вакансия: {vacancy}\n"
            f"ФИО: {fio}\n"
            f"Телефон: {phone}\n"
            f"Username: @{username if username else 'без username'}"
        )
        context.user_data.clear()

    else:
        await update.message.reply_text("Пожалуйста, выберите действие или нажмите /start.")

# --- Main ---

def main():
    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
