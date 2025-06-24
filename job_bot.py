import logging
import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Авторизация Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Подключение к таблицам
spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/10-sXX7zmsjxcLBGoua876P9eopBwPSe4f6P0NfmRDfY/edit")
sheet_vacancies = spreadsheet.worksheet("Вакансии")
sheet_questions = spreadsheet.worksheet("Вопросы")
sheet_applications = spreadsheet.worksheet("Отклики")

# Состояния диалога
ASK_NAME, ASK_PHONE, ASK_POSITION = range(3)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я бот кадрового агентства.\n"
        "Команды:\n"
        "/vacancies – Посмотреть вакансии\n"
        "/faq – Частые вопросы\n"
        "/apply – Оставить заявку"
    )

# Команда /vacancies
async def vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = sheet_vacancies.get_all_records()
    msg = ""
    for row in data:
        if row['СТАТУС'].strip().upper() == "ОТКРЫТА":
            msg += (
                f"📌 *{row['Вакансия']}*\n"
                f"💸 Часовая ставка: {row['Часовая ставка']}\n"
                f"🕐 Вахта 12ч (30/30): {row['Вахта по 12 часов (30/30)']}\n"
                f"🕦 Вахта 11ч (60/30): {row['Вахта по 11 ч (60/30)']}\n"
                f"📝 Описание: {row['Описание']}\n\n"
            )
    await update.message.reply_text(msg or "Нет открытых вакансий.", parse_mode='Markdown')

# Команда /faq
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = sheet_questions.get_all_records()
    msg = "\n\n".join([f"❓ {row['Вопрос']}\n💬 {row['Ответ']}" for row in data])
    await update.message.reply_text(msg or "Нет данных по вопросам.")

# Команда /apply
async def apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите ваше ФИО:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Введите ваш номер телефона:")
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("На какую вакансию вы хотите откликнуться?")
    return ASK_POSITION

async def get_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['position'] = update.message.text
    username = update.message.from_user.username or "—"
    today = datetime.today().strftime("%Y-%m-%d")

    sheet_applications.append_row([
        today,
        context.user_data['name'],
        context.user_data['phone'],
        context.user_data['position'],
        username
    ])
    await update.message.reply_text("Спасибо! Ваша заявка отправлена.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# Основная функция запуска
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("Переменная окружения BOT_TOKEN не установлена")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vacancies", vacancies))
    app.add_handler(CommandHandler("faq", faq))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("apply", apply)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ASK_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_position)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
